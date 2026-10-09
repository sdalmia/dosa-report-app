# Bought vs consumed: Dosa Coffee, 1–8 Oct 2026

Source: Restroworks files already on the box (Enterprise Consumption, daily warehouse Entry Reports, warehouse Indent stock-out, warehouse→CK Issue reports). Workbook: `consumption_vs_purchase_01-08Oct2026.xlsx` (sheets: summary, kolkata_items, delhi_items, stores, flags, notes).
"Raw" means the Food and Beverage super-categories. Semi Process is excluded.

## Headline (Rs)
| | Kolkata (East) | Delhi (North) |
|---|---|---|
| Warehouse GRN, all categories | 30.14L (+2.5k freight) | 27.10L (+7.5k freight) |
| GRN, raw only | 20.91L | 15.00L |
| Store direct purchases | 0 | 0 |
| Raw consumed: central kitchen | 5.40L | 5.68L |
| Raw consumed: stores | 7.10L | 6.28L |
| Raw bought minus consumed | **+8.41L** | **+3.05L** |
| Raw wastage | 44.1k | 37.4k |
| Warehouse outflow (indent to stores + issue to CK), all categories | 18.97L (12.33L + 6.64L) | 16.24L (11.64L + 4.60L)* |
| Warehouse closing change, all categories | 11.70L → 21.74L (**+10.04L**) | 14.90L → 26.18L (**+11.29L**) |
| …of which raw / packaging | +6.10L / +3.09L | +3.06L / +7.49L |
| Store physical gain/loss, raw | +10.7k | −1.93L (−1.80L is the Hershey's error) |

*Delhi outflow includes a false 1.80L Hershey's line (see #5).

## Threats and actions
1. **Warehouses absorbed about ₹21L in 8 days.** Combined warehouse stock grew from ₹26.6L to ₹47.9L. Purchases are running about 1.6x what goes out to stores and kitchens.
2. **Idli Daal is overbought in both cities.** Kolkata has 1,258 Kg (about 63 days of use) and Delhi has 1,320 Kg (about 65 days). Stock beyond 10 days is worth about ₹3.6L. Stop Idli Daal orders.
3. **Delhi coffee powder: 320 Kg (₹2.89L) was bought against 59 Kg used.** 270 Kg is in the warehouse, about 37 days of use. Stock beyond 10 days is about ₹1.77L.
4. **Kolkata White Butter: 420 Kg (₹2.83L) was bought against 105 Kg used.** 335 Kg is in the warehouse, about 25 days. Excess is about ₹1.37L. This is the same Hyperpure and Sanjay Patodia buying flagged earlier. Amul Butter (26 days, about ₹51k excess) and Idli Rice (15 days, about ₹41k) are also high.
5. **Delhi packaging: ₹10.5L was bought against ₹2.6L sent out.** Glen containers (250ml, 100ml, 500ml), small takeaway boxes, carry bags and flasks now cover 33–250 days. Stock beyond 30 days is about ₹4.9L. Kolkata has 102 days of flasks (about ₹43k) and 40 days of Ecolab sink detergent.
6. **A data-entry error is distorting Delhi.** On 2 Oct, indent IN-1854 sent 623 Ltr of Hershey's syrup (₹1.80L) to Sec 18 Noida. It should have been one 623 ml bottle. The return was then booked twice. Sec 18 now shows −622 Ltr / −₹1.80L closing and a −₹1.80L physical loss. Reverse it in Restroworks.
7. **Some items were used with no purchase, and stock went negative.** Possible missing GRNs or inflated recipes:
   - Kolkata Fried Chana Daal: 977 Kg (₹1.01L) used and none bought. The warehouse is at −432 Kg. Delhi used 930 Kg (₹1.15L), also with none bought.
   - Kolkata sunflower oil: −277 Ltr at the warehouse (−₹47k).
   - Kolkata coffee powder: −19.5 Kg. Kolkata Kashmiri chili: −25 Kg.
   - Delhi Dosa Daal: used 314 Kg, bought 60.
   - Find the GRNs or check the recipes.
8. **Semi-process recipes over-consume at stores.** Recipes booked ₹7.29L (Kolkata) and ₹8.63L (Delhi) against ₹5.51L and ₹5.47L received. Ideal closing is negative, and physical counts show a gain of ₹1.5L (Kolkata) and ₹1.7L (Delhi). This is the same BOM noise found on 15 Sep. Fix it before trusting store variance.

Other signals:
- Stores with the most negative closing: Rohini (−₹72k, mostly semi-process), Connaught Place (−₹32k) and Ideal Plaza (−₹28k).
- Biggest wastage: central-kitchen veg (Lauki, onion, pumpkin) and store fryer oil (9–13 Ltr per store).
- Chattarpur and GK1 Cloud Kitchen had zero stock activity.
- Stores consumed 80–100% of what the warehouse sent them, excluding semi-process. Quest Mall is lowest at 61%. Sec 18 shows 27% only because of the Hershey's error.

## Caveats
- Parsing: the Enterprise CSV and the Delhi indent CSV have an unquoted comma in "Pacific mall, Jasola" (940 and 315 rows). I merged the split fields and dropped no rows. If those rows are dropped, the Delhi dispatch figure falls by ₹1.06L. Total rows in the issue reports were removed. Entry Reports contain header, total and freight rows; I checked the dates in every file. The Delhi 01–03 file is not used. Dedupe found no true duplicates.
- GRN ties to Enterprise Purchase within paise, except Kolkata Rice Powder: Enterprise has 30 Kg / ₹3,000 more.
- Units: Black Salt, Mustard Seed, Dry Red Chili and Whole Methi are bought in Kg and stocked in gm (converted correctly). Paper Napkin is labelled Pkt in stock but Pc in GRN, with the same quantity.
- Warehouses and central kitchens have ₹0 physical count, so variance covers stores only. Central-kitchen semi-process production and dispatch is not in the report, so CK yield can't be measured.
- Values are at Restroworks average price, so closing is re-valued and flows don't tie exactly to the rupee. Quantities do balance at the warehouses.
- Days of cover are based on one week of usage.
