"""
Step 5 of the pipeline: publish results in three formats.

  outputs/charts/*.png     static charts for the README
  outputs/insights.md      auto-written headline findings
  dashboard/data.js        aggregated data for the interactive web dashboard
  powerbi/data/*.csv       star schema + marts for Power BI
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

# Colour roles (validated categorical palette, light mode)
INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#8a8984", "#e6e5e0"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]

plt.rcParams.update({
    "font.family": "sans-serif", "font.size": 10, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
    "xtick.color": INK2, "ytick.color": INK2, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False, "axes.titleweight": "bold",
    "axes.titlesize": 12, "axes.titlelocation": "left", "axes.titlecolor": INK,
    "figure.facecolor": "white", "axes.facecolor": "white", "legend.frameon": False,
})


def _save(fig, path: Path) -> None:
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def charts(con, r: dict, out: Path, demo: bool) -> None:
    out.mkdir(parents=True, exist_ok=True)
    tag = "  (synthetic demo data)" if demo else ""

    # 1. Monthly listening
    m = con.sql("SELECT * FROM mart_monthly").df()
    m["month"] = pd.to_datetime(m["year_month"])
    fig, ax = plt.subplots(figsize=(10, 3.6))
    ax.plot(m["month"], m["music_hours"], color=SERIES[0], lw=2, label="Music")
    ax.plot(m["month"], m["podcast_hours"], color=SERIES[1], lw=2, label="Podcasts")
    ax.set_title("Hours listened per month" + tag)
    ax.set_ylabel("hours")
    ax.legend(loc="upper left", ncols=2)
    _save(fig, out / "01_monthly_hours.png")

    # 2. Listening eras
    eras = r["eras"]
    fig, ax = plt.subplots(figsize=(10, 4.2))
    for i, e in enumerate(eras.itertuples()):
        sel = (m["year_month"] >= e.start) & (m["year_month"] <= e.end)
        ax.bar(m.loc[sel, "month"], m.loc[sel, "music_hours"], width=25, color=SERIES[i % 8],
               label=f"Era {e.era}: {e.signature_artists[0]}")
    ax.set_title("Listening eras, detected by clustering months by taste" + tag)
    ax.set_ylabel("music hours")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.1), fontsize=8, ncols=min(len(eras), 3))
    _save(fig, out / "02_eras.png")

    # 3. Artist survival by cohort
    fig, ax = plt.subplots(figsize=(7, 4.2))
    km = r["km_all"]
    ax.step(km["t"], km["survival"], where="post", color=INK2, lw=1.5, ls="--", label="All artists")
    for i, (name, k) in enumerate(r["km_cohorts"].items()):
        ax.step(k["t"], k["survival"], where="post", color=SERIES[i], lw=2, label=name)
        ax.fill_between(k["t"], k["lower"], k["upper"], step="post", color=SERIES[i], alpha=0.12, lw=0)
    ax.axhline(0.5, color=MUTED, lw=0.8)
    ax.set_xlim(0, 1500)
    ax.set_ylim(0, 1.02)
    ax.set_title("How long do artists survive in my rotation?" + tag)
    ax.set_xlabel("days since first play")
    ax.set_ylabel("share still in rotation")
    ax.legend()
    _save(fig, out / "03_artist_survival.png")

    # 4. Skip hazard
    fig, ax = plt.subplots(figsize=(7, 4.2))
    for i, (lbl, lt) in enumerate([("Shuffle on", r["lt_shuffle"]), ("Shuffle off", r["lt_chosen"])]):
        ax.plot(lt["x"] + 2.5, lt["q_x"], color=SERIES[i], lw=2, marker="o", ms=3, label=lbl)
    ax.set_title("Skip hazard: chance a song is skipped in each 5s band" + tag)
    ax.set_xlabel("seconds into the song")
    ax.set_ylabel("q(x) = skips ÷ still playing")
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.legend()
    _save(fig, out / "04_skip_hazard.png")

    # 5. Plays vs love
    t = con.sql("SELECT * FROM mart_track_rankings WHERE raw_plays >= 15").df()
    fig, ax = plt.subplots(figsize=(8, 4.6))
    ax.scatter(t["raw_plays"], t["love_score"], s=10, color=SERIES[0], alpha=0.35, lw=0)
    ax.set_xscale("log")
    hi = pd.concat([t.nsmallest(3, "rank_by_love"), t.nsmallest(3, "rank_by_plays")]).drop_duplicates("track_key")
    offsets = [(8, 6), (8, -12), (-8, 10), (8, 6), (8, -12), (8, 6)]
    for i, row in enumerate(hi.itertuples()):
        ax.scatter(row.raw_plays, row.love_score, s=36, color=SERIES[1], edgecolor="white", lw=1.5, zorder=3)
        dx, dy = offsets[i]
        ax.annotate(f"{row.track_name}  ({row.raw_plays} plays)", (row.raw_plays, row.love_score),
                    xytext=(dx, dy), textcoords="offset points", fontsize=8, color=INK,
                    ha="right" if dx < 0 else "left")
    ax.set_title("Most played vs most loved" + tag)
    ax.set_xlabel("total plays (log scale)")
    ax.set_ylabel("love score (credibility-weighted)")
    _save(fig, out / "05_plays_vs_love.png")

    # 6. Weekday x hour heatmap
    h = con.sql("SELECT * FROM mart_hour_weekday").df()
    grid = h.pivot_table(index="weekday_num", columns="start_hour", values="hours", fill_value=0)
    fig, ax = plt.subplots(figsize=(10, 3.2))
    ax.imshow(grid, aspect="auto", cmap=matplotlib.colors.LinearSegmentedColormap.from_list(
        "blue", ["#f4f8fd", "#9ec5f4", "#3987e5", "#184f95", "#0d366b"]))
    ax.set_yticks(range(7), ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
    ax.set_xticks(range(0, 24, 2), [f"{x:02d}:00" for x in range(0, 24, 2)])
    ax.grid(False)
    ax.set_title("When I listen (hours, local time)" + tag)
    _save(fig, out / "06_heatmap.png")


def dashboard_data(con, r: dict, path: Path, demo: bool) -> None:
    def recs(df):
        return json.loads(df.to_json(orient="records", date_format="iso"))

    def km(df, step=None):
        return recs(df[["t", "survival", "lower", "upper"]].round(4))

    data = dict(
        demo=demo,
        insights=r["insights"],
        kpis=con.sql("""SELECT round(sum(minutes_played)/60) AS hours,
                               count(*) FILTER (WHERE content_type='music' AND is_counted_play) AS plays,
                               count(DISTINCT artist_key) AS artists,
                               count(DISTINCT session_id) AS sessions,
                               round(avg(is_skip::INT) FILTER (WHERE content_type='music'), 3) AS skip_rate,
                               min(started_at)::DATE::VARCHAR AS first, max(started_at)::DATE::VARCHAR AS last
                        FROM fact_stream""").df().iloc[0].to_dict(),
        monthly=recs(con.sql("SELECT * FROM mart_monthly").df()),
        eras=recs(r["eras"]),
        heatmap=recs(con.sql("SELECT weekday_num, start_hour, hours FROM mart_hour_weekday").df()),
        km_all=km(r["km_all"]),
        km_cohorts={k: km(v) for k, v in r["km_cohorts"].items()},
        skip_shuffle=recs(r["lt_shuffle"].round(4)),
        skip_chosen=recs(r["lt_chosen"].round(4)),
        top_played=recs(con.sql("""SELECT track_name, artist_name, raw_plays, skip_rate, love_score, rank_by_love
                                   FROM mart_track_rankings ORDER BY rank_by_plays LIMIT 15""").df()),
        top_loved=recs(con.sql("""SELECT track_name, artist_name, raw_plays, skip_rate, love_score, rank_by_plays
                                  FROM mart_track_rankings ORDER BY rank_by_love LIMIT 15""").df()),
        artists=recs(con.sql("""SELECT artist_name, first_play::DATE::VARCHAR AS first_play,
                                       last_play::DATE::VARCHAR AS last_play, counted_plays, lifetime_days, churned
                                FROM mart_artist_lifetimes ORDER BY counted_plays DESC LIMIT 25""").df()),
        podcasts=recs(con.sql("SELECT * EXCLUDE (first_listen, last_listen), first_listen::VARCHAR AS first_listen, "
                              "last_listen::VARCHAR AS last_listen FROM mart_podcast_shows").df()),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("// Generated by src/publish.py - do not edit by hand\nwindow.DATA = "
                    + json.dumps(data, default=str, separators=(",", ":")) + ";\n")


def powerbi_csvs(con, r: dict, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    tables = ["fact_stream", "dim_date", "dim_artist", "dim_track", "dim_show",
              "mart_artist_lifetimes", "mart_track_rankings", "mart_podcast_shows", "mart_monthly"]
    for t in tables:
        con.execute(f"COPY {t} TO '{out / (t + '.csv')}' (HEADER, DELIMITER ',')")
    # Python-only results (survival curves, life tables, eras) - easier to chart than to rebuild in DAX
    km = pd.concat([r["km_all"].assign(cohort="All artists")]
                   + [v.assign(cohort=k) for k, v in r["km_cohorts"].items()])
    km.to_csv(out / "km_artist_survival.csv", index=False)
    pd.concat([r["lt_shuffle"].assign(group="Shuffle on"), r["lt_chosen"].assign(group="Shuffle off"),
               r["lt_all"].assign(group="All plays")]).to_csv(out / "skip_life_table.csv", index=False)
    r["eras"].assign(signature_artists=r["eras"]["signature_artists"].str.join(", "),
                     top_artists=r["eras"]["top_artists"].str.join(", ")).to_csv(out / "eras.csv", index=False)


def insights_md(r: dict, path: Path, demo: bool) -> None:
    lines = ["# Headline insights", ""]
    if demo:
        lines += ["> Generated from **synthetic demo data**. Rerun the pipeline with a real export to regenerate.", ""]
    for i in r["insights"]:
        lines.append(f"- **{i['title']}**: {i['text']}")
    lines += ["", "## Listening eras", "", "| Era | From | To | Months | Signature artists |", "|---|---|---|---|---|"]
    for e in r["eras"].itertuples():
        lines.append(f"| {e.era} | {e.start} | {e.end} | {e.months} | {', '.join(e.signature_artists)} |")
    path.write_text("\n".join(lines) + "\n")


def run(con, r: dict, root: Path, is_synthetic: bool) -> None:
    charts(con, r, root / "outputs" / "charts", is_synthetic)
    print("  ✓ charts        outputs/charts/*.png")
    insights_md(r, root / "outputs" / "insights.md", is_synthetic)
    print("  ✓ insights      outputs/insights.md")
    dashboard_data(con, r, root / "dashboard" / "data.js", is_synthetic)
    print("  ✓ dashboard     dashboard/data.js")
    powerbi_csvs(con, r, root / "powerbi" / "data")
    print("  ✓ Power BI      powerbi/data/*.csv")
