"""
Run the whole pipeline end to end.

    python -m src.pipeline              # use real export in data/raw/ if present, else synthetic
    python -m src.pipeline --source synthetic

Stages
  1. ingest   (Python)  JSON files  -> raw_streams table in DuckDB
  2. model    (SQL)     sql/01..06  -> staging, sessions, engagement, star schema, marts
  3. test     (SQL)     sql/07      -> data quality checks, stop on failure
  4. analyse  (Python)  survival curves, listening eras, headline insights
  5. publish  (Python)  charts (PNG), dashboard data, Power BI CSVs
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import duckdb

from src import ingest

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "spotify.duckdb"
SQL_DIR = ROOT / "sql"


def run_sql_models(con: duckdb.DuckDBPyConnection) -> None:
    for f in sorted(SQL_DIR.glob("0[1-6]_*.sql")):
        t = time.perf_counter()
        con.execute(f.read_text())
        print(f"  ✓ {f.name:<24} {time.perf_counter() - t:5.2f}s")


def run_checks(con: duckdb.DuckDBPyConnection) -> None:
    results = con.execute((SQL_DIR / "07_checks.sql").read_text()).fetchall()
    failed = [r for r in results if not r[1]]
    for name, passed, detail in results:
        print(f"  {'✓' if passed else '✗'} {name}  {detail}")
    if failed:
        raise SystemExit(f"{len(failed)} data quality check(s) failed")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["auto", "raw", "synthetic"], default="auto")
    ap.add_argument("--skip-analysis", action="store_true")
    args = ap.parse_args()

    kind, files = ingest.find_source(ROOT / "data" / "raw", ROOT / "data" / "synthetic", args.source)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH))

    print(f"[1/5] Ingest  ({kind} data, {len(files)} files)")
    n = ingest.load(files, con)
    print(f"  ✓ {n:,} rows loaded into raw_streams (IP / user-agent columns dropped)")

    print("[2/5] SQL models")
    run_sql_models(con)

    print("[3/5] Data quality checks")
    run_checks(con)

    if args.skip_analysis:
        return

    from src import analysis, publish
    print("[4/5] Analysis")
    results = analysis.run(con, is_synthetic=(kind == "synthetic"))

    print("[5/5] Publish")
    publish.run(con, results, ROOT, is_synthetic=(kind == "synthetic"))
    con.close()
    print("Done.")


if __name__ == "__main__":
    main()
