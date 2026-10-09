# Procurement drops

Put each export in this folder. The dashboard does not keep a raw table. It picks the newest file whose name matches a topic, using a date in the filename (`2026-10-08`, `8 Oct 2026`). A later dated file replaces the older one. CSV, XLS, and XLSX are read. A `.md` file in this folder is the human summary: its headings can be shown as threat headlines.

Until a file is here, the tile says no data. A blank cell is not shown as zero.

| Topic | Words to put in the filename | Columns the tile looks for |
| --- | --- | --- |
| Bought vs consumed | `bought`, `consumed` | city, bought, consumed |
| Warehouse stock | `warehouse` | item, closing, and change when the column exists |
| Overstock | `overstock` | item, days of cover, value beyond 10 days |
| No purchase or negative stock | `no-purchase`, `negative` | item, stock |
| Packaging cover | `packaging` | item, cover days |
| Wastage | `wastage` | item, wastage |
| Hershey's IN-1854 | `hershey`, `in-1854` | any cell that names IN-1854 |
| Base kitchen purchases | `purchase-summary`, `item-wise`, `base-kitchen` | item, amount |

Name the period in the filename so the tile can show it. Example: `bought-consumed-by-city-2026-10-08.csv`.
