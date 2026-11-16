-- =====================================================================
-- 03_sessions.sql  —  group plays into listening sessions
-- ---------------------------------------------------------------------
-- Classic "gaps and islands" problem using window functions:
--   1. LAG() finds when the previous play ended.
--   2. If the gap before this play is > 30 minutes, flag a new session.
--   3. A running SUM() of those flags gives every play a session number.
-- =====================================================================

CREATE OR REPLACE TABLE stream_sessions AS
WITH ordered AS (
    SELECT
        stream_id,
        started_at,
        ended_at,
        lag(ended_at) OVER (ORDER BY started_at, stream_id) AS prev_ended_at
    FROM stg_streams
    WHERE content_type <> 'unknown' AND ms_played > 0
),
flagged AS (
    SELECT
        *,
        CASE
            WHEN prev_ended_at IS NULL
              OR started_at - prev_ended_at > INTERVAL 30 MINUTE THEN 1
            ELSE 0
        END AS is_new_session
    FROM ordered
),
numbered AS (
    SELECT
        stream_id,
        sum(is_new_session) OVER (ORDER BY started_at, stream_id
                                  ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS session_id
    FROM flagged
)
SELECT
    stream_id,
    session_id,
    row_number() OVER (PARTITION BY session_id ORDER BY stream_id) AS position_in_session
FROM numbered;
