# Location Finder model inputs (as_of 2026-10-10)

Rules followed: only real numbers. Blank means unknown, never zero. Every row names its source.

## Sites covered (sites.csv, 95 rows)
- **29 stores** from site_pattern/site_pattern_matrix.csv.
  - True pins as instructed: Kalkaji 28.5406081,77.2569948; Paschim Vihar 28.674383,77.1039066; Shalimar Bagh 28.7018999,77.1657453; Gurgaon Sec 10 28.4400046,77.0068401.
  - Other pins are the Google Maps Dosa Coffee listings, except Calcutta Swimming Club, which is a manual approximate pin.
  - **Sec 15 Faridabad (02/0007) closes on 31 Oct 2026.** It is included and flagged in the `note` column.
  - Excluded: Food Truck (no fixed pin), and Chattarpur and GK1 (closed; they were never in the matrix).
- **66 candidate clusters** from site_pattern/candidate_clusters.csv, with IDs `NCR-Cnn` / `KOL-Cnn` followed by the area name. Two airport clusters (NCR-C07, KOL-C11) are flagged "airport concession".

## 1. competitors.csv (1,393 rows)
Scope: South Indian QSR and casual dining within 3 km of any site, deduped across sites. Each row also gives `nearest_site` and `nearest_site_m`.
- **Google Maps public listings (1,344 rows).** Searched on 2026-10-10:
  - Around every site (about 6 km viewport): "south indian restaurant" (2 pages), "dosa", "idli dosa udupi".
  - Across 52 city tiles: Sagar Ratna, Saravana Bhavan, Naivedyam, Dasaprakash, Mysore Canteen, Naan Dosa Pavs, idlyGo, Sambarpot, Mahabelly, Madras Coffee House, Carnatic Cafe, Chidambaram's, "Udupi restaurant", "Haldiram's south indian".
  - Kept a listing if its Google category is South Indian, Udupi, Kerala, Chettinad, Andhra, Tamil, Karnataka or Mangalorean, or its name matches the dosa/idli/udupi/madras/brand pattern.
  - Removed vada pav, Hyderabadi biryani, corporate offices and Dosa Coffee's own outlets.
  - Dedupe key is the Google place_id. `source` cites the place_id and the query.
- **OpenStreetMap (49 rows).** amenity = restaurant, fast_food, cafe or food_court with cuisine south_indian, udupi or kerala, or a South Indian name match. Source is the Geofabrik India extract dated 2026-10-08.
  - Rows within 150 m of a Google row with the same name prefix were dropped as duplicates.
  - OSM has no ratings, so rating and reviews are blank for these rows.
- **Ratings and reviews:**
  - `rating` is filled for 1,319 rows. These are Google stars at the time of search.
  - `reviews` is filled for 625 rows only. Google's list results often omit the review count. It was left blank rather than guessed.
- **Haldiram's (148 rows)** is included at brand level. Its cuisine reads "South Indian counter not verified per outlet", so drop it if you want strict South Indian only.
- **`brand` column:** chains are canonicalised. "independent" means a local udupi, dosa corner or similar. "Udupi Cafe/Udupi (generic name)" is a shared name, not one chain.
- **Not used:** brand store locators. The Sagar Ratna, Haldiram's and others' locator domains didn't resolve or render from the box, so Google Maps brand searches were used instead.
- **Known gap:** each Google query returns at most 20 results per page. In very dense areas (CP, Karol Bagh, Lajpat Nagar, Salt Lake) the 3 km count is a lower bound.
- **Earlier competitor results:** the "Rajouri Garden / Saket / Vasant Kunj / Lajpat Nagar / Salt Lake Sector V / Park Street" browser results weren't available as files on the box. Those areas are covered by the scrape above, since all of them are candidate clusters or stores.

## 2. delivery_inputs.csv (95 rows, one per site)
- **delivering_restaurants_3km is a PROXY, not aggregator data.** It counts OSM amenity = restaurant, fast_food or cafe (nodes and building ways) within 3 km, from the Geofabrik extract of 2026-10-08.
  - OSM coverage in India is incomplete and uneven. It is especially thin in Kolkata and in newer Gurgaon/Noida sectors. James Long Sarani shows 9, which is clearly under-mapped.
  - Use it as a relative signal within a city, never as an absolute count. It is filled for all 95 sites; low numbers are real OSM counts, not blanks.
- **residential_density** is in people per km². It is the mean over WorldPop 1 km grid cells whose centre lies within 3 km of the site.
  - Grid: `ind_ppp_2020_1km_Aggregated.tif` from data.worldpop.org (Global 2000–2020, UN-unadjusted).
  - Data year is 2020, so fast-growing areas are understated. That includes Gurgaon Sec 65–85, Noida 132–150, New Town, Greater Noida West and Sec 143. Filled for all 95 sites.
- New Town CK and Rosedale Plaza share a pin, so their values are identical.

## 3. metro_ridership.csv (320 rows = 313 stations, plus extra period rows for 7 stations)
- **Stations:**
  - All operational DMRC, Rapid Metro Gurgaon, NMRC Aqua and Kolkata Metro stations in OSM: 260 in NCR and 54 in Kolkata (Overpass, 2026-10-10).
  - Lines come from OSM route relations. Interchange nodes with the same name are merged.
  - RRTS / Namo Bharat is excluded. A few Aqua Line extension nodes are labelled "check if open".
  - Extra columns: `nearest_site`, `nearest_site_m`, `coord_source`.
- **daily_ridership is filled for only 23 rows (15 stations).** DMRC and Metro Railway Kolkata don't publish a current station-wise table. What exists:
  - **DMRC June 2026** average daily, from DMRC data reported by TOI on 20 Jul 2026 (rounded to 0.1 lakh): Botanical Garden 2.7 lakh, Kashmere Gate 2.6 lakh, Rajiv Chowk 2.1 lakh.
  - **DMRC October 2023** average daily, from DMRC data reported by TOI on 1 Dec 2023: Rajiv Chowk, Kashmere Gate, Mayur Vihar-I, Anand Vihar, Kalkaji Mandir, Inderlok, Kirti Nagar, Lajpat Nagar. The exact figures were read from the Wikipedia infoboxes that cite this TOI article; growth rates cross-check with the TOI text.
  - **Kolkata, single day 1 Sep 2025**, from Metro Railway's statement via PTI: Dum Dum, Esplanade, Rabindra Sadan, Sealdah, Howrah, Howrah Maidan. These are noisy single-day figures.
  - **Kolkata FY2023-24 annual ÷ 366:** Dum Dum, Esplanade, Rabindra Sadan, Sealdah, Salt Lake Sector V, Karunamoyee.
- `period` states exactly which figure each row is. Keep one period per station when modelling.
- **Not used:**
  - DMRC's monthly "Passenger Journey" PDF, which is line-level only.
  - DMRC's Jan 2015 station-wise RidershipDetails.pdf, which is now 404 and 11 years stale.
  - Durga Puja 5-day totals, which are festival-skewed.
- **Coverage near sites:**
  - Stores: 19 of 29 have a station within 1 km; 4 of those stations have ridership (CP, Ideal Plaza, Forum, Swimming Club).
  - Clusters: 32 of 66 have a station within 1 km; 5 have ridership (Salt Lake Sector V, Park Street, Lajpat Nagar, Moti Nagar via Kirti Nagar, Anand Vihar).

## 4. mall_inputs.csv (43 rows)
- **Rows:** 7 Dosa Coffee mall stores (every store with format=mall in site_pattern_matrix.csv: Forum, Manisquare, Quest, Rosedale, Ideal Plaza, Rangoli, Pacific Mall Jasola). Plus 31 malls inside 27 candidate clusters, and 5 reference malls (REF-*) named in the brief that are not clusters because they sit inside an existing Dosa Coffee catchment: DLF Mall of India, Ambience Gurugram, Acropolis, City Centre Salt Lake, City Centre New Town.
  - A cluster counts as a mall cluster when a Google Maps "Shopping mall" listing of a real mall sits within about 250 m of the cluster centre.
  - Some clusters have more than one mall, so they get one row per mall: NCR-C02 Saket (Select Citywalk, DLF Avenue, MGF Metropolitan) and NCR-C05 Vasant Kunj (Ambience, DLF Promenade, DLF Emporio). Join on site_id.
  - Gurgaon DLF (02/0009) is office_complex, not mall, so it is excluded.
- **aggregator_enabled:** Encoded as 1 (yes), 0 (no), blank (unknown), per Albus.
  - Own stores: from Posist raw/<code>/source_range_2026-09-09_to_10-08.tsv. Any Swiggy/Zomato sales means yes, zero means no. Forum and Quest are no (POS only). The evidence column gives the rupee value and order count for each channel.
  - Candidate malls: yes only when a Zomato page was fetched and shows an outlet whose address names the mall and that has a non-zero Zomato DELIVERY review count. The URL is either the Zomato "restaurants/in/<mall>" page or a single restaurant page.
  - Swiggy Dineout pages were not used as evidence, because they are dine-in only.
  - Rcube Monad is blank: the only page found shows 0 delivery reviews.
  - Elan Epic is "yes" on thin evidence (one outlet, 33 delivery reviews).
  - Caveat: delivery review counts add up over time, so an outlet could have stopped delivering since.
- **mall_google_rating / mall_google_reviews:** from the mall's own Google Maps listing (place_id is in source), via public search.
- **anchor_brands_inside:** a fixed list of 31 national F&B and retail anchors: McDonald's, KFC, Burger King, Domino's, Pizza Hut, Subway, Starbucks, Haldiram's, Wow! Momo, Chaayos, Barbeque Nation, Taco Bell, CCD, Theobroma, PVR INOX, Cinepolis, Shoppers Stop, Lifestyle, Pantaloons, Westside, Max, Zudio, H&M, Zara, M&S, Reliance Trends, Smart Bazaar, Spencer's, Croma, Uniqlo, Decathlon.
  - A brand counts when its Google Maps listing name or address names the mall and it is within 600 m of the mall pin. Google listings stand in for the mall directory.
  - Blank (not 0) where no listed brand matched: Ideal Plaza, DLF Emporio (luxury tenants not on the list) and Elan Epic.
  - Local anchors and luxury brands are not counted.
- **food_court:** yes when there is either a Google Maps listing at the mall named or categorised as a food court, or a Zomato outlet address containing "Food Court". The source column names the listing.
  - Blank where none was found. It is never set to "no" from absence.
- **Scripts:** build_malls.py, ../osm/malls.py (mall list), ../osm/mall_find.py, ../osm/mall_google.py, ../osm/mall_fix.py (Google), ../osm/zomato_mall.py, ../osm/zm_rest.py, ../osm/zm_run.py (Zomato, cached in ../zomato_cache).

## Main gaps
1. Station-level ridership for about 95% of stations. A DMRC RTI request for station-wise average daily entries and exits for FY2025-26 would fill it in one go, and Kolkata Metro the same.
2. Real aggregator counts. Swiggy/Zomato restaurant counts within 3 km would replace the OSM proxy.
3. Review counts for about 55% of competitor rows.
4. Population data year (2020). GHSL 2025 or the Census 2027 ward data would update it.
5. mall_inputs.csv:
   - Mall Google review counts are missing for 12 malls and ratings for 2 (Shipra, City Centre Dwarka). They need a browser lookup.
   - food_court is blank for 7 malls.
   - aggregator_enabled is blank for Rcube Monad.

Scripts: build_malls.py, build_competitors.py, build_delivery.py, build_metro.py, build_metro_out.py, plus ../osm/gm_comp.py (Google scrape, cached in ../gmaps_cache). Raw files are in raw/.

## v2 (10 Oct 2026)
Filled mall ratings/reviews and food_court from Google Maps browser checks. Shipra Mall and Gaur Central Mall reviews remain blank (no reliable Shopping mall listing). DLF Avenue food_court unclear.

## v3 (2 Nov 2026, monthly refresh)
- Sec 15 Faridabad (02/0007) removed: it stopped operating on 22 Oct 2026 and is out of the model from November 2026. Removed from sites.csv and delivery_inputs.csv. Competitor and metro rows whose nearest site was Faridabad were re-pointed to the nearest remaining site; competitor rows now more than 3 km from every site were dropped (out of scope). The October files are kept in prev_2026-10-10/.
- No new stores or candidate sites: the Posist store list (1 Nov 2026) and the Google Business Profile refresh of 2 Nov 2026 show the same 28 operating stores. No new openings, so openings.csv stays header-only.
- Figures not re-scraped this month (competitor ratings/reviews, OSM delivery proxy, WorldPop density, metro ridership) keep their 10 Oct 2026 as_of dates. Ridership sources were not re-checked; gaps stay blank.
