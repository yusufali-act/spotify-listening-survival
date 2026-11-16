-- =====================================================================
-- 01_staging.sql  —  clean, typed, consistently named stream table
-- ---------------------------------------------------------------------
-- Input : raw_streams (loaded by src/ingest.py, one row per playback)
-- Output: stg_streams
--
-- Key facts about Spotify's data that shape this step:
--   * `ts` is when playback STOPPED, not when it started. We derive the
--     start time by subtracting ms_played.
--   * One table mixes music, podcasts and audiobooks; which URI column is
--     filled tells us which one a row is.
--   * Platform strings changed format over the years ("Android OS 9 API 28
--     (samsung...)" in old exports vs "android" in new ones), so we bucket them.
-- =====================================================================

CREATE OR REPLACE TABLE stg_streams AS
SELECT
    row_number() OVER (ORDER BY ts_utc, source_file)            AS stream_id,
    ts_local - to_milliseconds(ms_played)                       AS started_at,
    ts_local                                                    AS ended_at,
    ms_played,
    CASE
        WHEN spotify_track_uri   IS NOT NULL THEN 'music'
        WHEN spotify_episode_uri IS NOT NULL THEN 'podcast'
        WHEN audiobook_title     IS NOT NULL THEN 'audiobook'
        ELSE 'unknown'
    END                                                         AS content_type,
    trim(master_metadata_track_name)                            AS track_name,
    trim(master_metadata_album_artist_name)                     AS artist_name,
    trim(master_metadata_album_album_name)                      AS album_name,
    spotify_track_uri                                           AS track_uri,
    trim(episode_name)                                          AS episode_name,
    trim(episode_show_name)                                     AS show_name,
    spotify_episode_uri                                         AS episode_uri,
    lower(coalesce(reason_start, 'unknown'))                    AS reason_start,
    lower(coalesce(reason_end,   'unknown'))                    AS reason_end,
    coalesce(shuffle, false)                                    AS shuffle,
    coalesce(skipped, false)                                    AS skipped_flag,
    coalesce(offline, false)                                    AS offline,
    coalesce(incognito_mode, false)                             AS incognito_mode,
    CASE
        WHEN platform ILIKE '%android%'                          THEN 'Android'
        WHEN platform ILIKE '%ios%' OR platform ILIKE '%iphone%' THEN 'iOS'
        WHEN platform ILIKE '%windows%'                          THEN 'Windows'
        WHEN platform ILIKE '%osx%' OR platform ILIKE '%mac%'    THEN 'Mac'
        WHEN platform ILIKE '%web%'                              THEN 'Web player'
        WHEN platform ILIKE '%cast%' OR platform ILIKE '%sonos%'
          OR platform ILIKE '%tv%'   OR platform ILIKE '%speaker%' THEN 'Cast / speaker'
        ELSE 'Other'
    END                                                         AS platform,
    conn_country,
    source_file
FROM raw_streams;
