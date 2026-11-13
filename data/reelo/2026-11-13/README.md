# Reelo pull for Command Centre - 13 Nov 2026 (Logan)

Range: 1 Jan to 12 Nov 2026 unless the filename says otherwise. Files named as_of_2026-11-13 are snapshots from the pull. Numbers are as Reelo exported or displayed them; anything unavailable is left blank. Aggregates only: no phone numbers, names or customer lists. Full file inventory and caveats: pull_log.txt.

## What's covered
1. Customers: customers_storewise / orders_storewise / average_spend_storewise give the full range for 24 stores (new, repeat, visits, covers, >2 visits, base, AOV). Monthly files are all-store for Jan-Oct, and Nov 1-12 is daily all-store. customer_lifetime_all_stores has lifetime averages. lapsed_all_stores has live counts: 30d 366,540; 60d (custom 14 Sep-13 Nov) 338,430; 90d 312,068. storewise_phone_capture_repeat_redemption is the 30-day store-wise file (phone capture %, repeat, redemption, rating).
2. Segments: segments_all_stores_last_year has 9 recommended segments, counts only (Reelo shows no spend). segments_Ideal_Plaza has the lifecycle segments with spend for one store only.
3. Campaigns: campaigns_manual.csv has 169 one-time campaigns from list cards. Store, sent, redeemed and credits are mostly blank because the list doesn't show them. auto_campaigns_detail has the 5 active and 1 inactive automations with funnels for 1 Nov 2025-12 Nov 2026 (read on 12 Nov). auto_campaigns_summary is the Oct 14-Nov 13 all-store summary.
4. Feedback: feedback_storewise covers the full range plus each month. Ratings, counts and positive/negative are included; Reelo shows no NPS. feedback_themes is qualitative, from recent comments, and not quantified.
5. Loyalty: loyalty_storewise covers the full range plus each month, with coins issued and redeemed, redemptions, revenue and customers. It has 27 rows because it includes legacy or inactive stores.
6. Credits: credits_balance_as_of_2026-11-13 and credits_manual (56 invoice rows, Jan-Nov 12).

## What failed or is missing
- Monthly per-store customer, order and AOV data (only all-store monthly).
- Per-store lapsed 30/60/90 counts, and spend for the all-store segments.
- Per-campaign stores, sent, redeemed and credits for one-time campaigns. The automations list didn't load for the full range.
- NPS (not in Reelo) and a counted complaint-theme breakdown.
- Closed stores (Faridabad, Chattarpur, GK1 CK) may appear in loyalty rows. Exclude them per standing rules.

## Weekly refresh
Logan's Monday routine (Weekly Reelo store performance, ~10:30 IST) already exports the 30-day and 7-day store-wise files and overwrites /workspace/dosa-coffee-mis/reelo/command-centre/reelo_storewise_latest.csv. A full history pull like this one is heavy (about 30 minutes in the browser), so refresh history monthly: append the closed month's store-wise feedback, loyalty, customer and order files and update credits. Ask Logan for a deeper pull when needed.
