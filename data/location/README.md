# Location learning files

Blank cells stay blank. A missing file means that input is data coming and is left out of the score. Do not write a zero in its place.

Months are `YYYY-MM`. The live score uses the latest model approved in the database. A refit is `proposed` until an owner approves it on the Location model page. Approving does not rewrite the JSON file. Render's disk is wiped on deploy, so the approval row has to live in the database. The default `sqlite:///app.db` file is wiped too. `GET /healthz/db` reports the dialect and whether that database is permanent, and never the URL. When the dialect is SQLite and `RENDER` is set, or `FLASK_ENV` is `production`, the Location model page hides Approve.

## store_features/YYYY-MM.csv

One row per trading store, at its Google pin. Closed stores are not included.

| Column | Meaning |
|---|---|
| as_of | Month of the snapshot, `YYYY-MM` |
| store_id | Store master id |
| store | Posist store name |
| city | City on the store master |
| market | `NCR` or `Kolkata` |
| format | `high_street`, `mall`, `cloud_kitchen`, or `metro` |
| lat, lng | Google pin. Blank when the pin is not on file |
| energy_of_6 | Energy sub-score, out of 6 |
| quality, anchor, diversity, transport | Sub-scores, 0 to 1 |
| nearby_reviews | Review count in the catchment |
| classic_score | Previous 0–10 score |
| energy, reviews, premium | Same signals on a 0–1 scale, as the formula uses them |
| cuisine_types | Cuisine types in the catchment |
| n_anchor_brands_500m | Anchor brands within 500 m |
| n_fnb_chains_500m | Food chains within 500 m |
| neighbour_brands | Neighbour brands and their distance |
| competitor_count | Strict South Indian competitors within 3 km. Haldiram's is left out. Blank when `inputs/competitors.csv` is missing. A real zero stays zero |
| competitor_count_all | Same radius, including Haldiram's |
| south_indian_density | Within-city percentile of `competitor_count`, from 0 to 1. Blank when the competitor file is missing |
| density_capped | `yes` when any one Google query has 20 or more results within 3 km, because that search is capped. `no` when the file is present and the site is under the cap. Blank when the file is missing |
| google_rating | Google rating. Blank when it is not on file |

## outcomes/YYYY-MM.csv

Joined to the snapshot. Manisquare and Forum leave `bills_per_trading_day` and `apb` blank.

| Column | Meaning |
|---|---|
| as_of, store_id, store, market, format | Same identity columns as the snapshot |
| gross_per_trading_day | Mean daily gross on days that have a gross figure |
| dine_in_share | POS gross divided by channel gross |
| aggregator_share | The rest of that channel gross |
| trend_4w | Last 7 days versus the 21 days before that, as a fraction. Blank when either window has no gross |
| famepilot_rating | Famepilot rating. Blank when the store has none |
| bills_per_trading_day | Mean daily bills. Blank for Manisquare and Forum |
| apb | Gross per day divided by bills per day. Blank for Manisquare and Forum, and blank when bills are blank |

## models/vYYYY-MM.json

| Field | Meaning |
|---|---|
| version | `vYYYY-MM` |
| status | `proposed` in the file. Approval is not written back into this file |
| as_of | Month |
| prior_version | The approved model this fit started from, or `prior` |
| n | Stores with a within-market rank of gross per day |
| spearman | Rank correlation of the fitted score with that within-market rank |
| loo_mae | Leave-one-store-out mean absolute error on the 0–1 rank |
| format_counts | Stores in each format |
| frozen_formats | Formats with fewer than 8 stores. Their weights stay at the prior |
| features_used | Signals that were present for every fitted store |
| weights | Non-negative weights by format |
| prior_weights | Weights the fit was pulled toward |
| backtest | One leave-one-store-out row per fitted store |
| approved_at | Left null in the file. The database stores the real approval time |

## Approval table `location_model_approval`

One row each time an owner approves a version. Revert fills `reverted_at` and `reverted_by` on that row. `latest_approved()` reads the newest row whose status is still `approved`.

| Column | Meaning |
|---|---|
| version | `vYYYY-MM`, matching the JSON file |
| status | `approved` or `reverted` |
| approved_by | Email of the owner who approved it |
| approved_at | When they approved it |
| reverted_at | When an owner undid it. Blank while it is still live |
| reverted_by | Email of the owner who undid it. Blank while it is still live |

Only an owner email can approve or revert. Undo returns to the previous approved version, or to the prior weights when there is no earlier approval. The Location model page lists every approve and revert.

A weight moves at most 20% from its prior in one month, and never below zero. A prior of 0 may rise by at most 0.20. The fit is one pooled model with a pull toward the shared weights and toward the prior, not a separate model per format and city.

`backtest` columns: `store`, `store_id`, `market`, `format`, `actual_rank`, `predicted_rank`, `decile_gap`, `miss`. `miss` is true when the gap is more than 1.5 rank-deciles.

## predictions.csv

One row each time someone scores a site.

| Column | Meaning |
|---|---|
| scored_at | Local time, `YYYY-MM-DD HH:MM:SS` |
| site_id | Format plus the pin, rounded to 5 decimals |
| site | Place name |
| lat, lng | Pin |
| format | Format that was scored |
| model_version | `prior` or the approved version |
| score | Format score, 0–10. Blank when there is no score |
| breakdown | Short text of each input and its points or status |

## openings.csv

Links a scored site to the store that opened there.

| Column | Meaning |
|---|---|
| site_id | Same id as `predictions.csv` |
| store_id | Store master id |
| open_date | `YYYY-MM-DD` |

The Location model page follows each row for 90 days from `open_date` and shows gross per trading day next to the predicted score. Days with no gross are not treated as zero.

## inputs/sites.csv

95 sites. Join the other input files on `site_id`. A live pin uses the site within 150 m.

| Column | Meaning |
|---|---|
| site_id | Store name, or a cluster id such as `NCR-C01` or `KOL-C12`, followed by the area |
| site_type | `store` (29 trading stores) or `candidate_cluster` (66 clusters, `NCR-C01`–`C54` and `KOL-C01`–`C12`) |
| lat, lng | Pin |
| city | `Delhi NCR` or `Kolkata`. Percentiles are within this city |
| note | Flags such as a closing date, an approximate pin, or an airport concession. Blank if none |

## inputs/competitors.csv

Optional. 1,393 rows of South Indian QSR and casual dining within 3 km of a site. If this file is missing, South Indian competitor density is data coming.

| Column | Meaning |
|---|---|
| brand | Chain name. `independent` is a local outlet. Haldiram's is brand-level only |
| name | Outlet name |
| lat, lng | Pin |
| city | City |
| cuisine | Cuisine text. Haldiram's says its South Indian counter was not verified per outlet |
| rating | Google stars. Blank if unknown |
| reviews | Review count. Blank on many rows. A blank is unknown, never zero |
| source | Google Maps query and place id, or OpenStreetMap. The query is the text in `search '...'` |
| as_of | `YYYY-MM-DD` |
| nearest_site | `site_id` of the nearest site |
| nearest_site_m | Metres to that site |

Strict density excludes any row whose brand contains Haldiram's. The all-in density keeps them. The score uses the within-city percentile of the strict count. A count of zero is a real zero.

Google returns at most 20 results a page. If any one query has 20 or more rows within 3 km, that site is marked capped and the count is a lower bound.

## inputs/delivery_inputs.csv

Optional. One row per site. If this file is missing, delivering restaurants and residential density stay data coming. A live pin must fall within 150 m of a row or both stay data coming.

| Column | Meaning |
|---|---|
| site_id | Same id as `sites.csv` |
| lat, lng | Pin |
| delivering_restaurants_3km | OpenStreetMap restaurants, fast food, and cafes within 3 km. A proxy, not an aggregator count. The score uses only the within-city percentile |
| residential_density | People per km², mean of WorldPop 2020 cells within 3 km. The score uses the within-city percentile. The people-per-km² figure stays in the detail |
| density_unit | Unit text for `residential_density` |
| source | How the two figures were built |
| as_of | `YYYY-MM-DD` |
| site_type | `store` or `candidate_cluster` |
| city | `Delhi NCR` or `Kolkata` |
| note | Blank if none |

WorldPop 2020 understates New Town, Greater Noida West, Gurgaon sectors 65–85, and Noida sectors 132–150 (including sector 143). Those sites say so on the score.

## inputs/metro_ridership.csv

Optional. If this file is missing, station distance and ridership stay data coming. Keep one row per station, the latest `period`.

| Column | Meaning |
|---|---|
| station | Station name |
| city | City |
| line | Line name |
| lat, lng | Station pin. Distance uses the nearest station |
| daily_ridership | Published daily ridership. Blank for most stations. A blank is unknown, never zero |
| period | Which published figure this row is. This text is the source shown on the score |
| source_url | Where the figure was read. Not shown on the score |
| nearest_site | `site_id` of the nearest site |
| nearest_site_m | Metres to that site |
| coord_source | Where the station pin came from |

Footfall stays at its prior weight and is data coming until at least 8 stores have a station with a figure within 1 km. A store counts when any station with a figure is within 1 km, even if a closer station has no figure. Today that is 4 stores: CP, Ideal Plaza, Forum, and Swimming Club.

## inputs/mall_inputs.csv

Optional. One row per mall. Drop a newer file in place of this one and rebuild the snapshot: the loader reads the file again and does not keep the previous counts. If this file is missing, mall reviews, anchors, and food court stay data coming.

| Column | Meaning |
|---|---|
| site_id | Store Posist name, a cluster id such as `NCR-C02` plus the area, or `REF-` for a reference mall |
| mall_name | Mall name |
| lat, lng | Mall pin |
| city | `Delhi NCR` or `Kolkata` |
| aggregator_enabled | `1` yes, `0` no, or blank. yes/no is read as 1/0. Blank is unknown and is left out, never scored as 0 |
| mall_google_reviews | The mall's own Google review count. The score uses the log scale. Blank is unknown, never zero |
| n_anchor_brands_inside | How many of 31 national anchor brands are inside the mall. Blank is unknown, never zero. The score is that count divided by 31 |
| food_court | `yes` or `no`, stored as 1 or 0. Blank is unknown. It is an optional flag at 5% of the mall prior, taken from transport |
| as_of | `YYYY-MM-DD` |

A row whose `site_id` starts with `REF-` is a nearby reference mall. It can be shown on the map. It is not trained on and it is not scored. The 7 store rows join to Store Master on the Posist name. The candidate rows join to `sites.csv` on `site_id`, including a cluster that has more than one mall. Mall stays frozen while it has fewer than 8 stores. Those stores still show the prior-weight score with these inputs. `models/v2026-10b.json` is that proposed refit. It is not approved.
