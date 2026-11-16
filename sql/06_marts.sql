-- =====================================================================
-- 06_marts.sql  —  analysis-ready summary tables ("marts")
-- ---------------------------------------------------------------------
-- Each mart answers one question. Python (charts, survival analysis), the
-- web dashboard and Power BI all read from these, so the business logic
-- lives in exactly one place.
-- =====================================================================

-- Q: How has my listening changed month by month?
CREATE OR REPLACE TABLE mart_monthly AS
WITH firsts AS (   -- the month each artist was first properly played (>= 30s)
    SELECT artist_key, min(date_trunc('month', started_at)) AS first_month
    FROM fact_stream WHERE content_type = 'music' AND is_counted_play
    GROUP BY artist_key
),
new_by_month AS (
    SELECT first_month AS month, count(*) AS new_artists FROM firsts GROUP BY 1
),
monthly AS (
    SELECT
        date_trunc('month', started_at)                                          AS month,
        round(sum(minutes_played) FILTER (WHERE content_type = 'music')   / 60, 1) AS music_hours,
        round(sum(minutes_played) FILTER (WHERE content_type = 'podcast') / 60, 1) AS podcast_hours,
        count(*) FILTER (WHERE content_type = 'music' AND is_counted_play)       AS counted_plays,
        count(DISTINCT artist_key) FILTER (WHERE is_counted_play)                AS distinct_artists,
        round(avg(is_skip::INT) FILTER (WHERE content_type = 'music'), 3)        AS skip_rate
    FROM fact_stream
    GROUP BY 1
)
SELECT
    strftime(m.month, '%Y-%m')       AS year_month,
    m.music_hours, m.podcast_hours, m.counted_plays, m.distinct_artists,
    coalesce(n.new_artists, 0)       AS new_artists,
    m.skip_rate
FROM monthly m
LEFT JOIN new_by_month n USING (month)
ORDER BY m.month;

-- Q: When do I listen? (weekday x hour heatmap)
CREATE OR REPLACE TABLE mart_hour_weekday AS
SELECT
    isodow(started_at)              AS weekday_num,
    strftime(started_at, '%a')      AS weekday_name,
    start_hour,
    round(sum(minutes_played) / 60, 1) AS hours
FROM fact_stream
GROUP BY ALL
ORDER BY weekday_num, start_hour;

-- Q: Which songs do I actually love vs. just hear a lot?
--
-- "love_score" = credibility-weighted average engagement per play.
-- A track played twice with perfect engagement shouldn't beat one played 300
-- times with great engagement, so we use Bühlmann-style credibility (the
-- same idea actuaries use to blend a small group's experience with the
-- overall book):
--     Z          = n / (n + k)              k = 20 plays
--     love_score = Z × track_average + (1 − Z) × overall_average
-- With 20 plays a track's own average counts for half; with 200 plays, ~91%.
CREATE OR REPLACE TABLE mart_track_rankings AS
WITH agg AS (
    SELECT
        t.track_key, t.track_name, a.artist_name,
        count(*)                                                     AS raw_plays,
        count(*) FILTER (WHERE f.is_counted_play)                    AS counted_plays,
        round(sum(f.minutes_played), 1)                              AS minutes,
        round(avg(f.is_skip::INT), 3)                                AS skip_rate,
        round(avg(f.completion), 3)                                  AS avg_completion,
        count(*) FILTER (WHERE f.intent = 'deliberate replay')       AS deliberate_replays,
        count(*) FILTER (WHERE f.intent = 'chosen')                  AS chosen_plays,
        round(sum(f.engagement_score), 2)                            AS engagement,
        avg(f.engagement_score)                                      AS avg_engagement
    FROM fact_stream f
    JOIN dim_track  t USING (track_key)
    JOIN dim_artist a ON a.artist_key = t.artist_key
    WHERE f.content_type = 'music'
    GROUP BY ALL
),
book AS (SELECT avg(engagement_score) AS overall_avg FROM fact_stream WHERE content_type = 'music'),
credible AS (
    SELECT agg.*,
           raw_plays / (raw_plays + 20.0)                                          AS credibility_z,
           credibility_z * avg_engagement + (1 - credibility_z) * book.overall_avg AS love_score
    FROM agg, book
)
SELECT
    track_key, track_name, artist_name, raw_plays, counted_plays, minutes, skip_rate,
    avg_completion, deliberate_replays, chosen_plays, engagement,
    round(avg_engagement, 3)                                AS avg_engagement,
    round(credibility_z, 3)                                 AS credibility_z,
    round(love_score, 3)                                    AS love_score,
    rank() OVER (ORDER BY raw_plays DESC, love_score DESC)  AS rank_by_plays,
    rank() OVER (ORDER BY love_score DESC, raw_plays DESC)  AS rank_by_love,
    rank_by_plays - rank_by_love                            AS rank_shift   -- + means underrated by play count
FROM credible;

-- Q: How long does an artist "live" in my rotation? (input to survival analysis)
-- An artist is born at their first counted play and "dies" if they go 90 days
-- without one before the data ends. Artists still being played are CENSORED:
-- we know they've lasted at least this long, not how long they'll last.
CREATE OR REPLACE TABLE mart_artist_lifetimes AS
WITH data_end AS (SELECT max(started_at) AS end_ts FROM fact_stream),
plays AS (
    SELECT artist_key, started_at, engagement_score,
           lead(started_at) OVER (PARTITION BY artist_key ORDER BY started_at) AS next_play
    FROM fact_stream
    WHERE content_type = 'music' AND is_counted_play
),
first_gap AS (   -- the first 90+ day silence ends the artist's first "life"
    SELECT artist_key, min(started_at) AS death_ts
    FROM plays, data_end
    WHERE coalesce(next_play, end_ts) - started_at > INTERVAL 90 DAY
    GROUP BY artist_key
)
SELECT
    a.artist_key,
    a.artist_name,
    min(p.started_at)                                           AS first_play,
    max(p.started_at)                                           AS last_play,
    count(*)                                                    AS counted_plays,
    round(sum(p.engagement_score), 1)                           AS engagement,
    year(min(p.started_at))                                     AS discovery_year,
    g.death_ts IS NOT NULL                                      AS churned,   -- 1 = event, 0 = censored
    date_diff('day', min(p.started_at), coalesce(g.death_ts, d.end_ts)) AS lifetime_days,
    count(*) FILTER (WHERE p.started_at <= coalesce(g.death_ts, d.end_ts)) AS plays_in_first_life,
    max(p.started_at) > coalesce(g.death_ts, d.end_ts) AS came_back
FROM plays p
JOIN dim_artist a USING (artist_key)
LEFT JOIN first_gap g USING (artist_key)
CROSS JOIN data_end d
GROUP BY a.artist_key, a.artist_name, g.death_ts, d.end_ts
HAVING count(*) >= 10;   -- only artists that genuinely entered rotation

-- Q: How quickly do I skip songs? (input to the skip "mortality table")
-- Each music play is a life: time = seconds played, event = skipped.
-- Plays that finished, or stopped because the app closed, are CENSORED.
CREATE OR REPLACE TABLE mart_skip_events AS
SELECT
    stream_id,
    least(ms_played / 1000.0, 600)  AS seconds_played,
    is_skip                         AS skipped,
    shuffle,
    intent
FROM fact_stream
WHERE content_type = 'music';

-- Q: Which podcasts stick, and which do I abandon?
CREATE OR REPLACE TABLE mart_podcast_shows AS
WITH data_end AS (SELECT max(started_at) AS end_ts FROM fact_stream),
episodes AS (
    SELECT show_key, episode_name,
           bool_or(reason_end = 'trackdone') AS finished,
           sum(minutes_played)               AS minutes,
           count(*)                          AS sittings
    FROM fact_stream WHERE content_type = 'podcast'
    GROUP BY ALL
)
SELECT
    s.show_name,
    count(*)                                  AS episodes_started,
    count(*) FILTER (WHERE e.finished)        AS episodes_finished,
    round(avg(e.finished::INT), 3)            AS completion_rate,
    round(sum(e.minutes) / 60, 1)             AS hours,
    round(avg(e.sittings), 2)                 AS avg_sittings_per_episode,
    min(f.first_listen)::DATE                 AS first_listen,
    max(f.last_listen)::DATE                  AS last_listen,
    CASE WHEN max(f.last_listen) >= d.end_ts - INTERVAL 60 DAY THEN 'Active'
         WHEN avg(e.finished::INT) < 0.5 THEN 'Abandoned'
         ELSE 'Finished / lapsed' END         AS status
FROM episodes e
JOIN dim_show s USING (show_key)
JOIN (SELECT show_key, min(started_at) AS first_listen, max(started_at) AS last_listen
      FROM fact_stream WHERE content_type = 'podcast' GROUP BY show_key) f USING (show_key)
CROSS JOIN data_end d
GROUP BY s.show_name, d.end_ts
ORDER BY hours DESC;

-- Q: What do my sessions look like?
CREATE OR REPLACE TABLE mart_sessions AS
SELECT
    session_id,
    min(started_at)                                    AS session_start,
    round(sum(minutes_played), 1)                      AS minutes,
    count(*)                                           AS plays,
    round(avg(is_skip::INT) FILTER (WHERE content_type = 'music'), 3) AS skip_rate,
    bool_or(content_type = 'podcast')                  AS has_podcast,
    mode(platform)                                     AS platform
FROM fact_stream
GROUP BY session_id;
