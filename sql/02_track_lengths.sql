-- =====================================================================
-- 02_track_lengths.sql  —  estimate how long each track is
-- ---------------------------------------------------------------------
-- The export never says how long a song is, only how long you played it.
-- But when a row ends with reason_end = 'trackdone' the song played to the
-- end, so ms_played on those rows ≈ the song's length. We take the median of
-- those plays; tracks that were never finished fall back to the longest play.
--
-- We need this to measure *completion*: 60 seconds of a 3-minute song is a
-- very different signal from 60 seconds of a 10-minute song.
-- =====================================================================

CREATE OR REPLACE TABLE track_lengths AS
SELECT
    track_uri,
    coalesce(
        median(ms_played) FILTER (WHERE reason_end = 'trackdone'),
        max(ms_played)
    )::BIGINT                                         AS est_length_ms,
    count(*) FILTER (WHERE reason_end = 'trackdone')  AS n_full_plays,
    n_full_plays > 0                                  AS length_is_reliable
FROM stg_streams
WHERE content_type = 'music'
GROUP BY track_uri;
