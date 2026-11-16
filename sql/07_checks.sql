-- =====================================================================
-- 07_checks.sql  —  data quality tests
-- ---------------------------------------------------------------------
-- Each row is one test. The pipeline stops if any test has passed = false.
-- This is the same idea as dbt tests: prove the transformations didn't
-- lose, duplicate or invent data.
-- =====================================================================

SELECT 'staging keeps every raw row' AS check_name,
       (SELECT count(*) FROM raw_streams) = (SELECT count(*) FROM stg_streams) AS passed,
       (SELECT count(*) FROM raw_streams)::VARCHAR || ' raw vs ' || (SELECT count(*) FROM stg_streams) || ' staged' AS detail
UNION ALL
SELECT 'fact = staged rows minus empty/unknown rows',
       (SELECT count(*) FROM fact_stream)
         = (SELECT count(*) FROM stg_streams WHERE content_type <> 'unknown' AND ms_played > 0),
       (SELECT count(*) FROM fact_stream)::VARCHAR || ' fact rows'
UNION ALL
SELECT 'total listening time preserved',
       (SELECT sum(ms_played) FROM fact_stream)
         = (SELECT sum(ms_played) FROM stg_streams WHERE content_type <> 'unknown' AND ms_played > 0),
       round((SELECT sum(ms_played) FROM fact_stream) / 3.6e6, 1)::VARCHAR || ' hours'
UNION ALL
SELECT 'stream_id is unique',
       (SELECT count(*) = count(DISTINCT stream_id) FROM fact_stream),
       ''
UNION ALL
SELECT 'every music play has a track and artist',
       (SELECT count(*) FROM fact_stream WHERE content_type = 'music' AND (track_key IS NULL OR artist_key IS NULL)) = 0,
       ''
UNION ALL
SELECT 'engagement score within [0, 1.5]',
       (SELECT count(*) FROM fact_stream WHERE engagement_score < 0 OR engagement_score > 1.5) = 0,
       ''
UNION ALL
SELECT 'every fact date exists in dim_date',
       (SELECT count(*) FROM fact_stream f ANTI JOIN dim_date d USING (date_key)) = 0,
       '';
