# Architecture: how the pieces fit together

A plain-English walkthrough of what each tool does, why it was chosen, and how to explain it.

---

## 1. The big picture: ELT

The project follows an **ELT** pattern (Extract, Load, Transform), which is how most modern data teams work:

```
Extract + Load (Python)   →   Transform (SQL)   →   Test (SQL)   →   Analyse (Python)   →   Present (Power BI / web)
```

The rule of thumb behind it is to **use each tool for what it's best at**:

| Job | Best tool | Why |
|---|---|---|
| Read messy files (nested JSON, time zones) | Python | SQL is awkward with files and formats |
| Clean, join, aggregate, reshape tables | **SQL** | Readable and declarative; it's what every analyst team uses |
| Statistics (survival curves, clustering) | Python | numpy and scikit-learn have the maths built in |
| Interactive business reporting | **Power BI** | Point-and-click exploration and the industry-standard model |
| A public demo anyone can open | HTML dashboard | No install and no licence; hosted free on GitHub Pages |

The **business logic lives in SQL**. Python only moves data in and runs the maths SQL can't do. That means the SQL files are the part to know well for interviews.

---

## 2. Walking through the pipeline

Run `python -m src.pipeline` and watch the console. Each numbered stage below matches a printed line.

### [1/5] Ingest: `src/ingest.py` (Python)
- Finds `Streaming_History_Audio_*.json` in `data/raw/` (your real data) or `data/synthetic/`.
- Keeps 19 useful columns and **never loads** IP address, user agent or username (privacy by design).
- Converts timestamps from UTC to UK time, so "8am" means 8am to you.
- Writes one table, `raw_streams`, into a DuckDB database file: `data/spotify.duckdb`.

**What's DuckDB?** A database that lives in a single file, with no server to install or run. Think of it as "SQLite for analytics". Its SQL is standard (very close to PostgreSQL and SQL Server), so everything you write here transfers to work.

### [2/5] SQL models: `sql/01` → `sql/06`
Each file builds on the previous one, like layers:

| File | Creates | The idea in one line |
|---|---|---|
| `01_staging.sql` | `stg_streams` | Rename, type and tidy columns; tag rows as music, podcast or audiobook; normalise platform names |
| `02_track_lengths.sql` | `track_lengths` | Estimate each song's length from plays that ran to the end |
| `03_sessions.sql` | `stream_sessions` | **Gaps and islands:** a 30-minute pause starts a new session (LAG + running SUM) |
| `04_engagement.sql` | `stream_engagement` | Score every play by how much was heard and whether it was chosen on purpose |
| `05_star_schema.sql` | `fact_stream`, `dim_*` | The model Power BI reads: one fact table, four dimension tables |
| `06_marts.sql` | `mart_*` | One table per question (monthly trends, rankings, lifetimes, podcasts...) |

SQL techniques worth being able to talk about: **CTEs** (`WITH`), **window functions** (`LAG`, `LEAD`, `ROW_NUMBER`, `RANK`, running `SUM`), **FILTER** clauses, **anti-joins**, and the **star schema**.

### [3/5] Data quality tests: `sql/07_checks.sql`
Seven tests that prove the transformations didn't lose, duplicate or invent data: row counts reconcile, total listening time is unchanged, IDs are unique, and every date exists in the calendar. If any test fails, the pipeline stops. Professional teams do the same thing with tools like dbt.

### [4/5] Analysis: `src/analysis.py` (Python)
- **Kaplan–Meier** written out by hand, so you can explain every line. It's the same estimator you'd use for mortality or lapse studies.
- **Skip life table**: `l_x`, `d_x`, `q_x`, `S_x`, set out exactly like a mortality table.
- **Era detection**: hierarchical clustering where months may only merge with neighbouring months.
- **Insights**: turns the numbers into plain-English sentences.

### [5/5] Publish: `src/publish.py`
Writes the same results in three formats: PNG charts for the README, `dashboard/data.js` for the web dashboard, and CSVs for Power BI.

---

## 3. Where Power BI fits

Power BI is the **presentation layer for business users**. It doesn't do the heavy lifting; SQL already did that. You import the clean star schema (`powerbi/data/*.csv`), set the relationships, add a handful of DAX measures and build report pages. This mirrors a real job, where a data warehouse feeds Power BI.

Step-by-step instructions are in [`powerbi_guide.md`](powerbi_guide.md).

Why also have a web dashboard? Recruiters won't install Power BI Desktop to open a `.pbix`. The web version is a link they can click. The Power BI file shows you can use the tool employers ask for.

---

## 4. How GitHub is used, and why

| Choice | Reason |
|---|---|
| **One repo with clear folders** (`sql/`, `src/`, `dashboard/`, `docs/`) | A reviewer can find the SQL in seconds |
| **README written as a case study** (question → method → findings) | Recruiters read the first screen; it needs to tell the story |
| **Raw data git-ignored** | Personal data never reaches GitHub; only aggregates are public |
| **Synthetic data generator** | Anyone can clone and run it; also proves the method works on known patterns |
| **CI workflow** (`.github/workflows/ci.yml`) | Every push re-runs the full pipeline and its tests on a fresh machine: proof it works and isn't just screenshots |
| **GitHub Pages** (`pages.yml`) | Hosts the dashboard free at `your-username.github.io/spotify-listening-survival` |
| **Commit history by stage** | Shows the build order: generator → ingest → SQL → analysis → dashboard → docs |

---

## 5. How it was built (the workflow)

1. **Understand the data contract.** Spotify's export schema is documented, so the generator could produce identical files before the real data existed.
2. **Build bottom-up and test each layer.** Ingest first, then each SQL file in turn, checking row counts as you go.
3. **Plant patterns, then check they're recovered.** The generator hides a burnout artist, an evergreen artist and an abandoned podcast. The analysis found all three, so the methods work.
4. **Separate logic from presentation.** The marts are the single source of truth; charts, the dashboard and Power BI all read from them.
5. **Automate.** One command (`make run`) rebuilds everything, so swapping in real data takes minutes.

---

## 6. When your real data arrives

```bash
# unzip the Spotify export into data/raw/, then:
make run
```
Everything recomputes. The synthetic-data banner disappears from the dashboard, and the charts and `insights.md` regenerate. Then update the "Key findings" section of the README with your real headlines.

## 7. Interview cheat-sheet

- *"Walk me through a SQL query you're proud of."* → `03_sessions.sql` (gaps and islands) or the credibility-weighted ranking in `06_marts.sql`.
- *"How do you ensure data quality?"* → `07_checks.sql` and the CI run on every push.
- *"How does your actuarial background help?"* → censoring, Kaplan–Meier, life tables and credibility theory, all applied outside insurance.
- *"Why a star schema?"* → Power BI's engine is designed for it: fast filtering, simple DAX, one-to-many relationships.
