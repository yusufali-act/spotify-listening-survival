-- =====================================================================
-- 04_engagement.sql  —  the Engagement Score
-- ---------------------------------------------------------------------
-- A raw play count treats every row equally: a song that auto-played for
-- 4 seconds before you skipped it counts the same as one you searched for and
-- listened to twice in a row. The Engagement Score tries to measure intent.
--
--   engagement_score = 0                               if played < 30 seconds
--                    = completion × intent_multiplier  otherwise
--
--   completion        = share of the track heard, capped at 1.0
--   intent_multiplier = 1.50  deliberate replay (pressed back to hear it again)
--                       1.25  chosen on purpose (clicked it in a list / search)
--                       1.00  arrived passively (autoplay, shuffle, next track)
--
-- 30 seconds is the threshold Spotify itself uses to count a "stream".
-- The weights are judgement calls; they live in this one file so they are
-- easy to challenge and change.
-- =====================================================================

CREATE OR REPLACE TABLE stream_engagement AS
WITH music AS (
    SELECT
        s.stream_id,
        s.track_uri,
        s.ms_played,
        s.reason_start,
        s.reason_end,
        s.skipped_flag,
        l.est_length_ms,
        lag(s.track_uri, 1) OVER w AS prev_track_1,
        lag(s.track_uri, 2) OVER w AS prev_track_2
    FROM stg_streams s
    JOIN track_lengths l USING (track_uri)
    WHERE s.content_type = 'music' AND s.ms_played > 0
    WINDOW w AS (ORDER BY s.started_at, s.stream_id)
),
scored AS (
    SELECT
        stream_id,
        least(ms_played / nullif(est_length_ms, 0), 1.0)                 AS completion,
        ms_played >= 30000                                               AS is_counted_play,
        (skipped_flag OR reason_end IN ('fwdbtn', 'backbtn'))            AS is_skip,
        CASE
            WHEN reason_start = 'backbtn'
             AND track_uri IN (prev_track_1, prev_track_2)               THEN 'deliberate replay'
            WHEN reason_start IN ('clickrow', 'remote')                  THEN 'chosen'
            ELSE 'passive'
        END                                                              AS intent
    FROM music
)
SELECT
    *,
    CASE intent WHEN 'deliberate replay' THEN 1.50
                WHEN 'chosen'            THEN 1.25
                ELSE 1.00 END                                            AS intent_multiplier,
    CASE WHEN is_counted_play THEN completion * intent_multiplier
         ELSE 0 END                                                      AS engagement_score
FROM scored;
