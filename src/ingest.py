"""
Step 1 of the pipeline: EXTRACT + LOAD (the "EL" in ELT).

Reads every Streaming_History_Audio_*.json file, keeps only the columns we need,
drops personal identifiers (IP address, user agent, username), converts the UTC
timestamps to local time, and loads the result into DuckDB as `raw_streams`.

All real *transformation* happens afterwards in SQL (see /sql) - Python is only
used here because reading nested JSON files and handling time zones is easier.
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd

LOCAL_TZ = "Europe/London"

# Columns we keep. Anything else in the export (ip_addr, user_agent_decrypted,
# username, ...) is deliberately never loaded.
KEEP = [
    "ts", "platform", "ms_played", "conn_country",
    "master_metadata_track_name", "master_metadata_album_artist_name",
    "master_metadata_album_album_name", "spotify_track_uri",
    "episode_name", "episode_show_name", "spotify_episode_uri",
    "audiobook_title", "audiobook_chapter_title",
    "reason_start", "reason_end", "shuffle", "skipped", "offline", "incognito_mode",
]


def find_source(raw_dir: Path, synthetic_dir: Path, source: str = "auto") -> tuple[str, list[Path]]:
    """Use the real export if present, otherwise fall back to synthetic data."""
    real = sorted(raw_dir.rglob("Streaming_History_Audio_*.json"))
    fake = sorted(synthetic_dir.glob("Streaming_History_Audio_*.json"))
    if source == "raw" or (source == "auto" and real):
        if not real:
            raise SystemExit(f"No Streaming_History_Audio_*.json files found under {raw_dir}/")
        return "real", real
    if not fake:
        raise SystemExit("No synthetic data yet - run: python -m src.generate_synthetic")
    return "synthetic", fake


def load(files: list[Path], con: duckdb.DuckDBPyConnection) -> int:
    frames = []
    for f in files:
        df = pd.DataFrame(json.loads(f.read_text(encoding="utf-8")))
        df = df.reindex(columns=KEEP)  # older exports lack some columns -> filled with NULL
        df["source_file"] = f.name
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)

    ts = pd.to_datetime(df["ts"], utc=True)
    df["ts_utc"] = ts.dt.tz_localize(None)
    df["ts_local"] = ts.dt.tz_convert(LOCAL_TZ).dt.tz_localize(None)
    df = df.drop(columns=["ts"])
    df["ms_played"] = pd.to_numeric(df["ms_played"], errors="coerce").fillna(0).astype("int64")
    for col in ["shuffle", "skipped", "offline", "incognito_mode"]:
        df[col] = df[col].astype("boolean")

    con.execute("CREATE OR REPLACE TABLE raw_streams AS SELECT * FROM df")
    return len(df)
