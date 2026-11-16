"""
Generate a realistic *synthetic* Spotify Extended Streaming History export.

Why this exists
---------------
Real exports take up to 30 days to arrive and contain personal data. This script
produces files in the exact same JSON schema (Streaming_History_Audio_*.json) so
the whole pipeline can be built, tested and demoed without anyone's private data.

It also *plants known patterns* so we can check the analysis recovers them:
  * 5 listening "eras" where genre taste shifts (the era detector should find them)
  * artist lifetimes drawn from a Weibull distribution, plus a few "evergreen"
    artists and one deliberate "burnout" artist (survival analysis should show it)
  * skip behaviour driven by a hidden per-track "appeal" score (the engagement
    score should rank high-appeal tracks above merely frequently-played ones)
  * podcasts, including one show that gets abandoned

Usage:  python -m src.generate_synthetic --out data/synthetic
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

UTC = timezone.utc
START = datetime(2016, 3, 1, tzinfo=UTC)
END = datetime(2026, 11, 1, tzinfo=UTC)
N_DAYS = (END - START).days

GENRES = ["Indie", "Pop", "UK Rap", "Lo-fi", "R&B", "Afrobeats"]

# (start date, genre preference weights in GENRES order) - the hidden "eras"
ERAS = [
    (datetime(2016, 3, 1, tzinfo=UTC), [5, 4, 1, 0.5, 1, 0.3]),   # indie/pop student years
    (datetime(2018, 6, 1, tzinfo=UTC), [1, 1, 6, 0.5, 1.5, 0.5]),  # UK rap
    (datetime(2020, 3, 15, tzinfo=UTC), [1, 0.5, 1, 6, 4, 0.5]),   # lockdown lo-fi + R&B
    (datetime(2021, 9, 1, tzinfo=UTC), [0.5, 1, 1.5, 1, 1.5, 6]),  # afrobeats
    (datetime(2024, 1, 1, tzinfo=UTC), [1, 3, 1, 1, 4, 2]),        # R&B / pop mix
]

ADJ = ["Neon", "Velvet", "Paper", "Silver", "Midnight", "Golden", "Hollow", "Crimson",
       "Static", "Lunar", "Wild", "Quiet", "Electric", "Faded", "Glass", "Northern",
       "Broken", "Sunday", "Analog", "Distant", "Honey", "Iron", "Coastal", "Violet"]
NOUN = ["Harbor", "Atlas", "Echoes", "Rivers", "Signals", "Tides", "Lanterns", "Wolves",
        "Avenue", "Satellites", "Gardens", "Machines", "Parade", "Ghosts", "Motel",
        "Horizon", "Kites", "Mirrors", "Arcade", "Saints", "District", "Comets"]
FIRST = ["Kofi", "Amara", "Leo", "Zara", "Theo", "Nia", "Jaden", "Maya", "Remi", "Tobi",
         "Ines", "Kai", "Sade", "Omar", "Lena", "Dami", "Ruby", "Yemi", "Cass", "Idris"]
LAST = ["Vale", "Okoro", "Hart", "Mensah", "Reyes", "Stone", "Adeyemi", "Cole", "Bloom",
        "Achebe", "Frost", "Lowe", "Banks", "Odu", "Wren", "Nash", "Ike", "Sol"]
WORDS = ["Late", "Night", "Drive", "Love", "Gold", "Rain", "City", "Lights", "Run",
         "Home", "Fire", "Blue", "Summer", "Dreams", "Heart", "Slow", "Fall", "Wave",
         "Back", "Again", "Alone", "Forever", "Sky", "Shadow", "Dance", "Free", "Lost",
         "Sweet", "Cold", "Water", "Paradise", "Signal", "Low", "High", "Motion"]

PODCASTS = [
    # name, active start, active end, episode minutes, completion propensity, weekly eps
    ("The Actuarial Hour", datetime(2017, 1, 1, tzinfo=UTC), END, 45, 0.85, 1.0),
    ("Morning Markets Brief", datetime(2019, 9, 1, tzinfo=UTC), END, 15, 0.92, 4.0),
    ("Deep Space Stories", datetime(2018, 4, 1, tzinfo=UTC), datetime(2019, 2, 1, tzinfo=UTC), 60, 0.55, 1.0),
    ("Football Talk Weekly", datetime(2016, 8, 1, tzinfo=UTC), END, 70, 0.6, 1.5),
    ("History in Ten", datetime(2020, 4, 1, tzinfo=UTC), datetime(2022, 6, 1, tzinfo=UTC), 25, 0.8, 2.0),
    ("Startup Diaries", datetime(2022, 3, 1, tzinfo=UTC), datetime(2022, 9, 1, tzinfo=UTC), 50, 0.3, 1.0),  # abandoned
    ("Mindful Minutes", datetime(2021, 1, 1, tzinfo=UTC), END, 12, 0.7, 1.5),
]


def uri(kind: str, key: str) -> str:
    """Deterministic fake Spotify URI (22 base62 chars) from a string key."""
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    n = int(hashlib.sha1(key.encode()).hexdigest(), 16)
    chars = []
    for _ in range(22):
        n, r = divmod(n, 62)
        chars.append(alphabet[r])
    return f"spotify:{kind}:{''.join(chars)}"


def era_prefs(rng_days: np.ndarray) -> np.ndarray:
    """Genre preference matrix (days x genres) with 60-day smooth transitions."""
    out = np.zeros((len(rng_days), len(GENRES)))
    starts = [(e[0] - START).days for e in ERAS]
    vecs = [np.array(e[1], float) / sum(e[1]) for e in ERAS]
    for i, d in enumerate(rng_days):
        idx = max(j for j, s in enumerate(starts) if s <= d)
        v = vecs[idx]
        if idx > 0 and d - starts[idx] < 60:  # blend from previous era
            w = (d - starts[idx]) / 60
            v = (1 - w) * vecs[idx - 1] + w * v
        out[i] = v
    return out


def build_catalogue(rng: np.random.Generator, n_artists: int = 320):
    names, seen = [], set()
    while len(names) < n_artists:
        if rng.random() < 0.5:
            n = f"{rng.choice(ADJ)} {rng.choice(NOUN)}"
        else:
            n = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        if n not in seen:
            seen.add(n)
            names.append(n)

    starts = [(e[0] - START).days for e in ERAS] + [N_DAYS]
    artists = []
    for rank, name in enumerate(names):
        genre = int(rng.integers(len(GENRES)))
        # discovery tends to happen in an era that favours the artist's genre
        era_w = np.array([ERAS[i][1][genre] for i in range(len(ERAS))], float)
        era_w *= np.diff(starts)
        era = rng.choice(len(ERAS), p=era_w / era_w.sum())
        discovered = int(rng.integers(starts[era], starts[era + 1]))
        evergreen = rng.random() < 0.07
        lifetime = 10**6 if evergreen else float(rng.weibull(0.9) * 420 + 20)
        artists.append(dict(
            name=name, genre=genre, pop=1.0 / (rank + 1) ** 0.75,
            discovered=discovered, dies=discovered + lifetime,
            tracks=[], albums=[f"{rng.choice(WORDS)} {rng.choice(WORDS)}" for _ in range(int(rng.integers(1, 4)))],
        ))

    # planted examples the analysis should surface
    artists[1].update(name="Kofi Hart", pop=0.22, discovered=(datetime(2016, 4, 1, tzinfo=UTC) - START).days, dies=10**6, genre=4)
    artists[2].update(name="Glass Comets", discovered=(datetime(2019, 1, 10, tzinfo=UTC) - START).days,
                      dies=(datetime(2019, 5, 20, tzinfo=UTC) - START).days, genre=2, pop=3.0)  # burnout

    for a in artists:
        n_tracks = int(3 + rng.geometric(0.12))
        for t in range(n_tracks):
            title = f"{rng.choice(WORDS)} {rng.choice(WORDS)}"
            a["tracks"].append(dict(
                name=title, album=str(rng.choice(a["albums"])),
                dur_ms=int(np.clip(rng.normal(205, 45), 95, 420) * 1000),
                appeal=float(rng.beta(2, 2)),
                weight=1.0 / (t + 1) ** 0.8,
                uri=uri("track", f"{a['name']}|{title}|{t}"),
            ))
    return artists


def generate(out_dir: Path, seed: int = 42) -> int:
    rng = np.random.default_rng(seed)
    artists = build_catalogue(rng)
    days = np.arange(N_DAYS)
    prefs = era_prefs(days)

    pop = np.array([a["pop"] for a in artists])
    genre = np.array([a["genre"] for a in artists])
    disc = np.array([a["discovered"] for a in artists])
    dies = np.array([a["dies"] for a in artists])

    # trips abroad change conn_country for a week or two
    trips = []
    for y in range(2016, 2027):
        for _ in range(int(rng.integers(1, 3))):
            s = (datetime(y, int(rng.integers(1, 13)), 1, tzinfo=UTC) - START).days + int(rng.integers(0, 20))
            trips.append((s, s + int(rng.integers(5, 15)), str(rng.choice(["ES", "FR", "US", "AE", "TR", "NG", "IT"]))))

    def country(day: int) -> str:
        for s, e, c in trips:
            if s <= day < e:
                return c
        return "GB"

    def platform(day: int) -> str:
        year = 2016 + day / 365
        if rng.random() < 0.18:
            return str(rng.choice(["windows", "web_player", "cast_to_device"]) if year < 2021 else rng.choice(["osx", "web_player", "cast_to_device"]))
        return "android" if year < 2020.5 else "ios"

    rows: list[dict] = []
    recent: dict[str, tuple[int, float]] = {}  # track uri -> (last day, decayed play count)
    in_progress: dict[str, tuple[int, int]] = {}  # podcast -> (episode number, position ms)
    hour_p = np.array([1, .5, .3, .2, .2, .4, 1, 3, 5, 3, 2, 2, 3, 2.5, 2, 2, 2.5, 4, 4.5, 3.5, 3.5, 4, 3.5, 2])
    hour_p /= hour_p.sum()

    def base_row(ts: datetime, plat: str, day: int) -> dict:
        return {
            "ts": ts.strftime("%Y-%m-%dT%H:%M:%SZ"), "platform": plat, "ms_played": 0,
            "conn_country": country(day), "ip_addr": f"203.0.113.{int(rng.integers(1, 255))}",
            "master_metadata_track_name": None, "master_metadata_album_artist_name": None,
            "master_metadata_album_album_name": None, "spotify_track_uri": None,
            "episode_name": None, "episode_show_name": None, "spotify_episode_uri": None,
            "audiobook_title": None, "audiobook_uri": None, "audiobook_chapter_uri": None,
            "audiobook_chapter_title": None, "reason_start": None, "reason_end": None,
            "shuffle": False, "skipped": False, "offline": False, "offline_timestamp": None,
            "incognito_mode": False,
        }

    for day in days:
        date = START + timedelta(days=int(day))
        weekend = date.weekday() >= 5
        alive = (disc <= day) & (dies >= day)
        if not alive.any():
            continue
        honeymoon = 1 + 2.5 * np.exp(-(day - disc) / 40.0)
        w = pop * prefs[day, genre] * honeymoon * alive
        w = w / w.sum()

        growth = 1.2 + 1.0 * day / N_DAYS
        n_sessions = rng.poisson(growth * (1.25 if weekend else 1.0))

        # --- podcasts: weekday commute or weekend morning ---
        active = [p for p in PODCASTS if p[1] <= date < p[2]]
        for name, _, _, mins, completion, per_week in active:
            if rng.random() > per_week / 7:
                continue
            ep, pos = in_progress.get(name, (int((date - START).days / (7 / per_week)), 0))
            dur = int(mins * 60_000 * rng.uniform(0.8, 1.2)) if pos == 0 else pos + int(mins * 60_000 * 0.5)
            hour = 8 if not weekend else int(rng.integers(9, 12))
            t = date + timedelta(hours=hour, minutes=int(rng.integers(0, 50)))
            remaining = max(dur - pos, 60_000)
            if rng.random() < completion:
                played, reason_end = remaining, "trackdone"
                in_progress.pop(name, None)
            else:
                played = int(remaining * rng.uniform(0.05, 0.7))
                reason_end = str(rng.choice(["endplay", "logout", "fwdbtn"], p=[.6, .25, .15]))
                if rng.random() < completion:  # will resume later
                    in_progress[name] = (ep, pos + played)
                else:
                    in_progress.pop(name, None)
            r = base_row(t + timedelta(milliseconds=played), platform(int(day)), int(day))
            r.update(ms_played=int(played), episode_name=f"{name} - Episode {ep}", episode_show_name=name,
                     spotify_episode_uri=uri("episode", f"{name}|{ep}"),
                     reason_start="clickrow" if pos == 0 else "playbtn", reason_end=reason_end)
            rows.append(r)

        # --- music sessions ---
        for _ in range(n_sessions):
            t = date + timedelta(hours=int(rng.choice(24, p=hour_p)), minutes=int(rng.integers(0, 60)),
                                 seconds=int(rng.integers(0, 60)))
            plat = platform(int(day))
            shuffle = bool(rng.random() < 0.45)
            n_tracks = int(rng.geometric(1 / 11))
            reason_start = str(rng.choice(["clickrow", "playbtn", "appload"], p=[.6, .25, .15]))
            prev = None
            cur_artist = None
            replay = None
            for i in range(n_tracks):
                if replay is not None:
                    a_idx, trk = replay
                    replay = None
                else:
                    if cur_artist is not None and not shuffle and rng.random() < 0.35:
                        a_idx = cur_artist
                    else:
                        a_idx = int(rng.choice(len(artists), p=w))
                    tw = np.array([x["weight"] for x in artists[a_idx]["tracks"]])
                    trk = artists[a_idx]["tracks"][int(rng.choice(len(tw), p=tw / tw.sum()))]
                cur_artist = a_idx

                last_day, cnt = recent.get(trk["uri"], (int(day), 0.0))
                cnt = cnt * math.exp(-(day - last_day) / 14) + 1
                recent[trk["uri"]] = (int(day), cnt)
                fatigue = 0.03 * max(cnt - 3, 0)
                p_skip = float(np.clip(0.6 - 0.65 * trk["appeal"] + 0.08 * shuffle + fatigue, 0.03, 0.92))

                last = i == n_tracks - 1
                if rng.random() < p_skip:
                    played = rng.exponential(7000) if rng.random() < 0.6 else rng.uniform(15000, trk["dur_ms"] * 0.9)
                    played = int(min(played, trk["dur_ms"] - 1000))
                    back = rng.random() < 0.08 and prev is not None
                    reason_end, skipped = ("backbtn" if back else "fwdbtn"), True
                    if back:
                        replay = prev
                elif last and rng.random() < 0.5:
                    played = int(trk["dur_ms"] * rng.uniform(0.1, 0.95))
                    reason_end, skipped = str(rng.choice(["endplay", "logout", "unexpected-exit"], p=[.6, .3, .1])), False
                else:
                    played = trk["dur_ms"] + int(rng.integers(-400, 400))
                    reason_end, skipped = "trackdone", False
                    if trk["appeal"] > 0.8 and rng.random() < 0.12:
                        replay = (a_idx, trk)  # loved it - went back to hear it again

                t = t + timedelta(milliseconds=played)
                r = base_row(t, plat, int(day))
                r.update(ms_played=played, master_metadata_track_name=trk["name"],
                         master_metadata_album_artist_name=artists[a_idx]["name"],
                         master_metadata_album_album_name=trk["album"], spotify_track_uri=trk["uri"],
                         reason_start=reason_start, reason_end=reason_end, shuffle=shuffle, skipped=skipped,
                         offline=bool(rng.random() < 0.03), incognito_mode=bool(rng.random() < 0.002))
                rows.append(r)
                if reason_end not in ("trackdone", "fwdbtn", "backbtn"):
                    break
                reason_start = "backbtn" if replay is not None else ("trackdone" if reason_end == "trackdone" else "fwdbtn")
                if rng.random() < 0.06:
                    reason_start = "clickrow"  # user picked something specific mid-session
                prev = (a_idx, trk)
                t = t + timedelta(milliseconds=int(rng.integers(0, 1500)))

        # real exports contain a sprinkle of empty rows
        if rng.random() < 0.05:
            r = base_row(date + timedelta(hours=int(rng.integers(0, 24))), "android", int(day))
            r.update(reason_start="unknown", reason_end="unknown")
            rows.append(r)

    rows.sort(key=lambda r: r["ts"])
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("Streaming_History_Audio_*.json"):
        old.unlink()
    chunk = 16_000  # real exports split files at roughly this size
    for i in range(0, len(rows), chunk):
        part = rows[i:i + chunk]
        y0, y1 = part[0]["ts"][:4], part[-1]["ts"][:4]
        name = f"Streaming_History_Audio_{y0}-{y1}_{i // chunk}.json" if y0 != y1 else f"Streaming_History_Audio_{y0}_{i // chunk}.json"
        (out_dir / name).write_text(json.dumps(part, indent=1))
    return len(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="data/synthetic", type=Path)
    ap.add_argument("--seed", default=42, type=int)
    args = ap.parse_args()
    n = generate(args.out, args.seed)
    print(f"Wrote {n:,} synthetic stream rows to {args.out}/")
