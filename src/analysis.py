"""
Step 4 of the pipeline: statistical analysis in Python.

SQL prepared the inputs (marts); Python does the parts SQL is bad at:

  * kaplan_meier()      survival curve with Greenwood confidence intervals
  * skip_life_table()   a "mortality table" for songs: the chance of being
                        skipped in each 5-second band, given you got that far
  * detect_eras()       find listening "eras" by clustering months by taste
  * headline insights   plain-English findings, generated from the numbers

Kaplan-Meier is written out by hand (about 15 lines of numpy) rather than
imported, so the method is visible and checkable.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics import silhouette_score


# ----------------------------------------------------------------------
# Survival analysis
# ----------------------------------------------------------------------
def kaplan_meier(durations: np.ndarray, events: np.ndarray) -> pd.DataFrame:
    """
    Kaplan-Meier estimator.

    At each time t where at least one "death" happens:
        n_t = number still at risk (not yet died or censored) just before t
        d_t = number of deaths at t
        S(t) = S(t-) × (1 - d_t / n_t)

    Greenwood's formula gives the variance:  S(t)² × Σ d / (n (n - d))
    """
    durations = np.asarray(durations, float)
    events = np.asarray(events, bool)
    times = np.unique(durations[events])
    rows, s, g = [(0.0, len(durations), 0, 1.0, 1.0, 1.0)], 1.0, 0.0
    for t in times:
        n = int((durations >= t).sum())
        d = int(((durations == t) & events).sum())
        s *= 1 - d / n
        if n > d:
            g += d / (n * (n - d))
        se = s * np.sqrt(g)
        rows.append((t, n, d, s, max(s - 1.96 * se, 0), min(s + 1.96 * se, 1)))
    return pd.DataFrame(rows, columns=["t", "at_risk", "events", "survival", "lower", "upper"])


def median_survival(km: pd.DataFrame) -> float | None:
    below = km[km["survival"] <= 0.5]
    return float(below["t"].iloc[0]) if len(below) else None


def survival_at(km: pd.DataFrame, t: float) -> float:
    return float(km[km["t"] <= t]["survival"].iloc[-1])


def skip_life_table(df: pd.DataFrame, band: int = 5, max_s: int = 240) -> pd.DataFrame:
    """
    Actuarial life table where each play is a "life" and a skip is a "death".

        l_x = plays still going at second x        (exposed to risk)
        d_x = plays skipped between x and x+band   (deaths)
        q_x = d_x / l_x                            (hazard: chance of skip in this band)
        S_x = Π (1 - q)                            (share of plays surviving to x)
    """
    secs = df["seconds_played"].to_numpy()
    skipped = df["skipped"].to_numpy(bool)
    out, s = [], 1.0
    for x in range(0, max_s, band):
        l = int((secs >= x).sum())
        d = int(((secs >= x) & (secs < x + band) & skipped).sum())
        q = d / l if l else 0.0
        out.append((x, l, d, q, s))
        s *= 1 - q
    return pd.DataFrame(out, columns=["x", "l_x", "d_x", "q_x", "S_x"])


# ----------------------------------------------------------------------
# Listening eras
# ----------------------------------------------------------------------
def detect_eras(monthly_artist: pd.DataFrame, min_k: int = 3, max_k: int = 6) -> pd.DataFrame:
    """
    Each month becomes a vector of "share of listening time per artist".
    Hierarchical clustering with a *connectivity constraint* (a month may only
    merge with the month next to it) repeatedly joins the two most similar
    neighbouring stretches. That guarantees every era is a continuous run of
    months. The number of eras is the k with the best silhouette score.
    """
    pivot = monthly_artist.pivot_table(index="year_month", columns="artist_name",
                                       values="minutes", aggfunc="sum", fill_value=0).sort_index()
    top = pivot.sum().nlargest(80).index
    X = pivot[top].to_numpy(float)
    X = X / np.clip(np.linalg.norm(X, axis=1, keepdims=True), 1e-9, None)  # L2 -> ward ≈ cosine
    n = len(X)
    conn = np.eye(n, k=1) + np.eye(n, k=-1)

    best = None
    for k in range(min_k, min(max_k, n - 1) + 1):
        labels = AgglomerativeClustering(n_clusters=k, linkage="ward", connectivity=conn).fit_predict(X)
        score = silhouette_score(X, labels, metric="cosine")
        if best is None or score > best[0]:
            best = (score, k, labels)
    _, k, labels = best

    months = pivot.index.to_list()
    eras, start = [], 0
    for i in range(1, n + 1):
        if i == n or labels[i] != labels[start]:
            block = pivot.iloc[start:i]
            share = block.sum() / block.sum().sum()
            overall = pivot.sum() / pivot.sum().sum()
            lift = (share / overall.clip(lower=1e-9)) * share  # distinctive AND big in this era
            eras.append(dict(
                era=len(eras) + 1, start=months[start], end=months[i - 1], months=i - start,
                hours=round(float(block.to_numpy().sum()) / 60, 1),
                top_artists=share.nlargest(5).index.to_list(),
                signature_artists=lift.nlargest(3).index.to_list(),
            ))
            start = i
    return pd.DataFrame(eras)


# ----------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------
def run(con, is_synthetic: bool) -> dict:
    lifetimes = con.sql("SELECT * FROM mart_artist_lifetimes").df()
    km_all = kaplan_meier(lifetimes["lifetime_days"], lifetimes["churned"])

    # cohort analysis: do artists I discover now last as long as those from earlier years?
    lifetimes["cohort"] = pd.cut(lifetimes["discovery_year"], [2000, 2018, 2021, 2100],
                                 labels=["Discovered ≤2018", "2019–2021", "2022+"])
    km_cohorts = {str(c): kaplan_meier(g["lifetime_days"], g["churned"])
                  for c, g in lifetimes.groupby("cohort", observed=True) if len(g) >= 15}

    skips = con.sql("SELECT * FROM mart_skip_events").df()
    lt_all = skip_life_table(skips)
    lt_shuffle = skip_life_table(skips[skips["shuffle"]])
    lt_chosen = skip_life_table(skips[~skips["shuffle"]])

    monthly_artist = con.sql("""
        SELECT strftime(started_at, '%Y-%m') AS year_month, a.artist_name, sum(minutes_played) AS minutes
        FROM fact_stream JOIN dim_artist a USING (artist_key)
        WHERE content_type = 'music' GROUP BY ALL
    """).df()
    eras = detect_eras(monthly_artist)

    print(f"  ✓ artist survival: {len(lifetimes)} artists, median lifetime {median_survival(km_all)} days")
    print(f"  ✓ skip life table: {len(skips):,} plays")
    print(f"  ✓ listening eras: {len(eras)} detected")
    for e in eras.itertuples():
        print(f"      Era {e.era}: {e.start} → {e.end}  ({', '.join(e.signature_artists)})")

    insights = build_insights(con, lifetimes, km_all, km_cohorts, lt_all, lt_shuffle, lt_chosen, eras)
    return dict(lifetimes=lifetimes, km_all=km_all, km_cohorts=km_cohorts, lt_all=lt_all,
                lt_shuffle=lt_shuffle, lt_chosen=lt_chosen, eras=eras, insights=insights)


def build_insights(con, lifetimes, km_all, km_cohorts, lt_all, lt_shuffle, lt_chosen, eras) -> list[dict]:
    """Turn the numbers into short, plain-English findings."""
    out = []
    tot = con.execute("""SELECT round(sum(minutes_played)/60) h, min(started_at)::DATE d0, max(started_at)::DATE d1,
                     count(DISTINCT artist_key) artists FROM fact_stream""").fetchone()
    out.append(dict(title="The big number",
                    text=f"{tot[0]:,.0f} hours of listening between {tot[1]:%b %Y} and {tot[2]:%b %Y}, "
                         f"across {tot[3]:,} artists."))

    med = median_survival(km_all)
    one_yr = survival_at(km_all, 365)
    out.append(dict(title="How long an artist lasts",
                    text=f"Half of the artists that enter my rotation are gone within {med:.0f} days "
                         f"(no plays for 90 days). Only {one_yr:.0%} are still in rotation after a year."))

    if len(km_cohorts) >= 2:
        meds = {k: median_survival(v) for k, v in km_cohorts.items()}
        txt = ", ".join(f"{k}: {v:.0f} days" if v else f"{k}: not reached" for k, v in meds.items())
        out.append(dict(title="Is my taste getting more fickle?",
                        text=f"Median artist lifetime by discovery cohort: {txt}."))

    burnout = lifetimes[lifetimes["churned"]].assign(
        intensity=lambda d: d["plays_in_first_life"] / d["lifetime_days"].clip(lower=1)
    ).nlargest(1, "intensity").iloc[0]
    out.append(dict(title="Biggest burnout",
                    text=f"{burnout.artist_name}: {burnout.plays_in_first_life:,} plays packed into "
                         f"{burnout.lifetime_days} days ({burnout.first_play:%b %Y}), then silence."))

    evergreen = lifetimes[~lifetimes["churned"]].nlargest(1, "lifetime_days").iloc[0]
    out.append(dict(title="The evergreen",
                    text=f"{evergreen.artist_name} has stayed in rotation for "
                         f"{evergreen.lifetime_days / 365.25:.1f} years and counting."))

    early = lt_all[lt_all["x"] < 30]
    skip_30 = 1 - lt_all[lt_all["x"] == 30]["S_x"].iloc[0]
    peak = lt_all.loc[lt_all["q_x"].idxmax()]
    out.append(dict(title="The skip mortality table",
                    text=f"{skip_30:.0%} of plays are skipped within 30 seconds. The riskiest moment is "
                         f"{peak.x:.0f}–{peak.x + 5:.0f}s, when {peak.q_x:.0%} of songs still playing get skipped. "
                         f"Past the first minute, risk falls sharply."))

    sh30 = 1 - lt_shuffle[lt_shuffle["x"] == 30]["S_x"].iloc[0]
    ch30 = 1 - lt_chosen[lt_chosen["x"] == 30]["S_x"].iloc[0]
    out.append(dict(title="Shuffle as a risk factor",
                    text=f"On shuffle, {sh30:.0%} of songs are skipped in the first 30s vs {ch30:.0%} "
                         f"with shuffle off."))

    habit = con.execute("""SELECT track_name, artist_name, rank_by_plays, skip_rate FROM mart_track_rankings
                       WHERE rank_by_plays <= 5 ORDER BY skip_rate DESC LIMIT 1""").fetchone()
    out.append(dict(title="Most played ≠ most loved",
                    text=f"\"{habit[0]}\" by {habit[1]} is my #{habit[2]} most-played track, but I skip it "
                         f"{habit[3]:.0%} of the time. A habit, not a favourite."))

    loved = con.execute("""SELECT track_name, artist_name, rank_by_plays, love_score FROM mart_track_rankings
                       ORDER BY rank_by_love LIMIT 1""").fetchone()
    out.append(dict(title="The real favourite",
                    text=f"By credibility-weighted engagement, the most loved track is \"{loved[0]}\" by "
                         f"{loved[1]}, only #{loved[2]} by raw play count."))

    pod = con.execute("""SELECT show_name, completion_rate FROM mart_podcast_shows
                     WHERE status = 'Abandoned' ORDER BY hours DESC LIMIT 1""").fetchone()
    if pod:
        out.append(dict(title="The podcast I gave up on",
                        text=f"{pod[0]}: I finished only {pod[1]:.0%} of the episodes I started."))

    out.append(dict(title="Listening eras",
                    text=f"Clustering months by taste finds {len(eras)} distinct eras. The longest ran "
                         f"{eras.loc[eras['months'].idxmax(), 'start']} → {eras.loc[eras['months'].idxmax(), 'end']}."))
    return out
