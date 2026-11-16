# Building the Power BI report (about 1–2 hours)

Power BI Desktop is Windows-only. Use a work PC, Parallels or UTM on a Mac, or a Windows cloud PC.

## 0. Get the data
Run the pipeline (`make run`), then copy the `powerbi/data/` folder to the Windows machine.

| File | Role |
|---|---|
| `fact_stream.csv` | **Fact**: one row per play |
| `dim_date.csv`, `dim_artist.csv`, `dim_track.csv`, `dim_show.csv` | **Dimensions** |
| `mart_track_rankings.csv`, `mart_artist_lifetimes.csv`, `mart_podcast_shows.csv`, `mart_monthly.csv` | Pre-built summaries |
| `km_artist_survival.csv`, `skip_life_table.csv`, `eras.csv` | Python results (survival curves, life table, eras) |

## 1. Load
**Home → Get data → Text/CSV**, then load each file. In Power Query check the types:
- `fact_stream.started_at` → Date/Time; `is_counted_play`, `is_skip`, `shuffle` → True/False
- `dim_date.date` → Date

## 2. Model (Model view)
Create these relationships (all **many-to-one, single direction**, from fact to dimension):

```
fact_stream[date_key]    →  dim_date[date_key]
fact_stream[track_key]   →  dim_track[track_key]
fact_stream[artist_key]  →  dim_artist[artist_key]
fact_stream[show_key]    →  dim_show[show_key]
mart_track_rankings[track_key] → dim_track[track_key]
```
Then select `dim_date`, choose **Table tools → Mark as date table** and pick the `date` column. Sort `month_name` by `month` and `weekday_name` by `weekday_num`.

## 3. DAX measures
Create a blank table called `_Measures` to hold them.

```DAX
Hours Listened = DIVIDE ( SUM ( fact_stream[ms_played] ), 3600000 )

Counted Plays = CALCULATE ( COUNTROWS ( fact_stream ), fact_stream[is_counted_play] = TRUE () )

Music Plays = CALCULATE ( COUNTROWS ( fact_stream ), fact_stream[content_type] = "music" )

Skip Rate =
DIVIDE (
    CALCULATE ( COUNTROWS ( fact_stream ), fact_stream[is_skip] = TRUE (), fact_stream[content_type] = "music" ),
    [Music Plays]
)

Distinct Artists = DISTINCTCOUNT ( fact_stream[artist_key] )

Avg Engagement =
CALCULATE ( AVERAGE ( fact_stream[engagement_score] ), fact_stream[content_type] = "music" )

-- Bühlmann credibility: blend a track's own average with the overall average
Love Score =
VAR n        = [Music Plays]
VAR ownAvg   = [Avg Engagement]
VAR bookAvg  = CALCULATE ( [Avg Engagement], REMOVEFILTERS ( dim_track ), REMOVEFILTERS ( dim_artist ) )
VAR Z        = DIVIDE ( n, n + 20 )
RETURN Z * ownAvg + ( 1 - Z ) * bookAvg

Hours YoY % =
VAR cur  = [Hours Listened]
VAR prev = CALCULATE ( [Hours Listened], SAMEPERIODLASTYEAR ( dim_date[date] ) )
RETURN DIVIDE ( cur - prev, prev )

Deliberate Replays = CALCULATE ( COUNTROWS ( fact_stream ), fact_stream[intent] = "deliberate replay" )
```

## 4. Report pages

**Page 1: Overview**
- Cards: Hours Listened, Counted Plays, Distinct Artists, Skip Rate
- Line chart: `dim_date[year_month]` × Hours Listened, with `content_type` as the legend
- Matrix heatmap: rows `weekday_name`, columns `fact_stream[start_hour]`, values Hours Listened (conditional formatting → background colour scale)
- Slicers: `dim_date[year]`, `fact_stream[platform]`

**Page 2: Favourites vs habits**
- Table from `mart_track_rankings`: track, artist, raw_plays, skip_rate, love_score, rank_by_plays, rank_by_love
- Scatter: X = raw_plays (log axis), Y = love_score, details = track_name
- Bar: top 15 tracks by **Love Score** next to top 15 by **Music Plays**

**Page 3: Survival**
- Line chart from `km_artist_survival.csv`: X = `t`, Y = `survival`, legend = `cohort` (turn on the stepped line option)
- Line chart from `skip_life_table.csv`: X = `x`, Y = `q_x`, legend = `group`
- Table from `mart_artist_lifetimes`: artist, first_play, lifetime_days, churned, came_back

**Page 4: Eras & podcasts**
- Table from `eras.csv`
- Table from `mart_podcast_shows` with conditional formatting on completion_rate

## 5. Save & share
Save as `powerbi/listening_survival.pbix`. Take a screenshot of each page into `docs/img/` and add them to the README.

> Note: the `.pbix` embeds the data. With real data, only commit it if you're comfortable sharing play-level listening history. Screenshots are the safer option.
