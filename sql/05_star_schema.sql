-- =====================================================================
-- 05_star_schema.sql  —  the model Power BI reads
-- ---------------------------------------------------------------------
-- A star schema: one central FACT table (one row per play, with the numbers)
-- surrounded by DIMENSION tables (the things you slice by: date, artist,
-- track, podcast show). This is the shape Power BI is designed around:
-- each dimension relates one-to-many to the fact table.
-- =====================================================================

-- ---------- dim_date: one row per calendar day ----------
CREATE OR REPLACE TABLE dim_date AS
WITH bounds AS (
    SELECT min(started_at)::DATE AS d0, max(ended_at)::DATE AS d1 FROM stg_streams
)
SELECT
    CAST(strftime(d, '%Y%m%d') AS INTEGER) AS date_key,
    d::DATE                                AS date,
    year(d)                                AS year,
    quarter(d)                             AS quarter,
    month(d)                               AS month,
    strftime(d, '%b')                      AS month_name,
    strftime(d, '%Y-%m')                   AS year_month,
    isodow(d)                              AS weekday_num,   -- 1 = Monday
    strftime(d, '%a')                      AS weekday_name,
    isodow(d) IN (6, 7)                    AS is_weekend
FROM bounds, range(d0, d1 + INTERVAL 1 DAY, INTERVAL 1 DAY) AS t(d);

-- ---------- dim_artist ----------
CREATE OR REPLACE TABLE dim_artist AS
SELECT
    dense_rank() OVER (ORDER BY artist_name) AS artist_key,
    artist_name
FROM (SELECT DISTINCT artist_name FROM stg_streams WHERE content_type = 'music' AND artist_name IS NOT NULL);

-- ---------- dim_track ----------
CREATE OR REPLACE TABLE dim_track AS
SELECT
    dense_rank() OVER (ORDER BY t.track_uri) AS track_key,
    t.track_uri,
    t.track_name,
    t.album_name,
    a.artist_key,
    l.est_length_ms,
    l.length_is_reliable
FROM (
    SELECT track_uri, any_value(track_name) AS track_name,
           any_value(album_name) AS album_name, any_value(artist_name) AS artist_name
    FROM stg_streams WHERE content_type = 'music' GROUP BY track_uri
) t
JOIN dim_artist a USING (artist_name)
JOIN track_lengths l USING (track_uri);

-- ---------- dim_show (podcasts) ----------
CREATE OR REPLACE TABLE dim_show AS
SELECT dense_rank() OVER (ORDER BY show_name) AS show_key, show_name
FROM (SELECT DISTINCT show_name FROM stg_streams WHERE content_type = 'podcast');

-- ---------- fact_stream: one row per play ----------
CREATE OR REPLACE TABLE fact_stream AS
SELECT
    s.stream_id,
    CAST(strftime(s.started_at, '%Y%m%d') AS INTEGER) AS date_key,
    s.started_at,
    hour(s.started_at)                                AS start_hour,
    ss.session_id,
    ss.position_in_session,
    s.content_type,
    t.track_key,
    t.artist_key,
    sh.show_key,
    s.episode_name,
    s.ms_played,
    round(s.ms_played / 60000.0, 3)                   AS minutes_played,
    e.completion,
    coalesce(e.is_counted_play, s.ms_played >= 30000) AS is_counted_play,
    coalesce(e.is_skip, false)                        AS is_skip,
    e.intent,
    coalesce(e.engagement_score, 0)                   AS engagement_score,
    s.reason_start,
    s.reason_end,
    s.shuffle,
    s.platform,
    s.conn_country
FROM stg_streams s
JOIN stream_sessions ss       USING (stream_id)
LEFT JOIN stream_engagement e USING (stream_id)
LEFT JOIN dim_track t         ON s.track_uri = t.track_uri
LEFT JOIN dim_show sh         ON s.show_name = sh.show_name;
