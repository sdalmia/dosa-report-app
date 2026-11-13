# Dosa Coffee licence and compliance table

Built 13 November 2026 (Asia/Calcutta). Status is calculated as of **13 November 2026**.

Output: `/workspace/compliance/2026-11-13/licences.csv`

Columns: `store`, `city`, `licence_type`, `licence_no`, `issued`, `expiry`, `status`, `source_file`, `source_modified`, `notes`.

Dates are ISO `YYYY-MM-DD`. Drive `modifiedTime` values in UTC were converted to the Asia/Calcutta calendar date for `source_modified`. Status values: `valid`, `expiring_30d`, `expiring_90d`, `expired`, `missing`, `unknown`. Dates were never invented: if a source had no readable issue or expiry date, those cells are blank and status is `unknown` (or `missing` when the source itself says pending / not available / under process / on hold).

Store names follow the Command Centre store master where possible. Closed stores are listed only in the gaps section below, not in the CSV.

## Row counts

- Total data rows: **233** (plus header)
- Kolkata: **113**
- NCR: **120**
- By status: valid 73, unknown 97, missing 51, expired 9, expiring_30d 3, expiring_90d 0

## Sources used

Read-only via the Google Drive connector. Nothing was shared, edited or moved.

### Trackers (spreadsheets)

| File | Drive id | Modified (Asia/Calcutta date) | Owner / last editor | How it was used |
|---|---|---|---|---|
| LICENSE | `1qdT_JAtZLGHwTLBEeK6-U74nIFNs4-qH5YyzUns7QbU` | 2026-07-16 | Soni Jaiswal (created and last edited that day) | **Primary Kolkata source.** Clean dated table of trade, FSSAI, fire, PPL, police, metrology and shops & establishment for 17 Dalgreen Foods outlets, including licence numbers. |
| Copy of KOLKATA LICENSE COMPLINCE STATUS.xlsx | `1gkNt1XakyCeqPK_zk62Sr7sP6HCzWP7p` | 2026-07-18 | Soni Jaiswal | Inspected because the file date is two days later than LICENSE. Sheet1 and "All License with Expiry" are **staler** than LICENSE (Ideal Plaza FSSAI still shown as 31.08.2025, fire as 15.10.2024). Not used as the current source. Licence numbers and some issue dates were cross-checked against the May original below. |
| KOLKATA LICENSE COMPLINCE STATUS.xlsx | `1_uFG2YIUhbvRh5qbQCoUEO49VxhsqSOq` | 2026-05-27 | anisha.gupta | Supporting Kolkata detail: trade / FSSAI / fire / PPL / S&E licence numbers and a few issue dates (for example Lake Road fire no. 211822406300002228, issued 16.01.2025). Sheet1 dates are mixed; prefer LICENSE for current expiries. |
| Dosa Coffee-Kolkata Stores Legal License Update | `1rd_Tt0yo420_U2tjhczSXIRie3H9fSjnlk1SYw5IJj8` | 2026-03-18 | Owner Siddhant Dalmia; last edited by Anup Ghosh | Historical snapshot tabs through **12-01-2026**. Used only to flag possible year typos in the July LICENSE shops-issued remarks (see gaps). First tab dated "13-Nov-2026" is a remaining-days formula, not a refresh; that tab's data is from 2022. |
| License Sheet _Dosa Coffee.xlsx | `1V8KZ5ZxksN_tfdROFdrADDP0yEMd8agm` | 2025-09-20 | (in the Kolkata licence folder) | Older Kolkata snapshot. Not used for current expiries. |
| Delhi NCR/ License Validity Date | `1LsTC_BEzT5q94ufKOhAVgcw8D9AxtBweyFPlCA64eLU` | 2026-05-22 | Owner Abhishek Tyagi; last edited by Sanjoy Roy | **Most recent NCR tracker found.** Lives in folder "License Status Delhi NCR Excel Sheet" (`1kEWT_hkne2T-jMoFE_OSbXMBlDaL1nAP`). Sheet1 is a Yes / Pending / Not Available / WIP / N/A grid for 12 outlets and 9 licence types. **It has no issue or expiry dates**, despite the file name. Used for presence/absence of non-FSSAI licences only. |
| License Status / Abhishek | `1esa7dsztGDvdRlU7Mvnsa2SBP4KNNoOeKnfuSpw51qY` | 2024-09-04 | Abhishek Tyagi | 2024 NCR status by store (Done / Pending / Not Required), no dates. Treated as stale. Not used for current expiries. |
| DelhiNCR License Cost Sheet | `1rfj46XNrH9DXGT2PLBwbFOX_JdjjgCX8Rj8iev9uafc` | 2026-01-28 | Abhishek Tyagi | Payment ledger, not a validity tracker. Used only as context that Paschim Vihar and Gurgaon Sec-15 FSSAI fees were paid after the last certificates on Drive. |

### NCR certificates (PDFs used for dated FSSAI / health-trade rows)

| File | Drive id | Modified | Store and facts taken |
|---|---|---|---|
| 2027 FSSAI Pacific.pdf | `1NMY-_jXtj-2itwHpa4wMRnr-GR_SBRTt` | 2026-09-08 | Pacific Mall Jasola FSSAI 13324010000650, issued 2026-09-08, valid to 2027-09-16 |
| FSSAI MT 2027.pdf | `1XvsC9Za_KF6eGh6lubahNySc_8aMT8y9` | 2026-08-07 | Model Town FSSAI 13324008000535, issued 2026-08-07, valid to 2027-08-21 |
| FSSAI License Sec 31 GGN 26-27.pdf | `16j-F6CKh_DeM-BS49o9EsRPutkkQxcRR` | 2026-06-19 | Sec 31 Gurgaon FSSAI 10826005000737, issued 2026-04-16, fee paid to 2027-04-15 |
| FSSAI Sec18 2026.pdf | `18yy1nVMhiGwsBsj7vNTd5wRBdptcBp--` | 2026-06-02 | Sec 18 Noida FSSAI 12723055000731, issued 2026-06-02, valid to 2027-06-03 |
| FSSAI DLF 2026.pdf | `1KLKUt_sTuGJHKLEWHSJdSqFdp-dr1aIK` | 2026-06-02 | Gurgaon DLF (Building 5, Cyber City, DLF Phase III) FSSAI 10824005000755, issued 2026-06-02, valid to 2027-06-03 |
| htl_license.pdf | `1BqNhUPm4zwju4eAWwhy6pm47wXnRRpl4` | 2026-05-01 | Shalimar Bagh MCD Health Trade License HTLMCD32026041004782, generated 2026-04-29, valid to 2029-03-31. Text extracted successfully (not a blank scan). |
| license.pdf (Rohini renewal) | `1RBbY3ig2iKfFdVWggtJXDuJytQqzQhSp` | 2026-04-08 | Rohini Sec-7 FSSAI 13324001000284, issued 2026-04-08, valid to 2027-04-15 |
| FSSAI License Shalimar Bagh 26-27 (1).pdf | `1d_SA5O8st_66x9qdOkD4yI0XU_BGfyFm` | 2026-03-19 | Shalimar Bagh FSSAI 13326001000099, issued 2026-02-17, valid to 2027-02-16 |
| FSSAI Sec10A.pdf | `1yadwij-5jyKaE6Q5WwsP2Bn_si9OrsQp` | 2025-12-12 | Gurgaon Sec 10 (SCO 33, Sector 10A HUDA Market) FSSAI 10825005002315, issued 2025-12-12, valid to 2026-12-11 |
| FSSAI 2026.pdf | `1xWhsrD0omyBVACIvi8LijVQQ3bRuaa1b` | 2025-11-13 | Sec 143 Noida FSSAI 12723055001338, issued 2025-11-09, valid to **2026-11-12** (expired as of 13 Nov) |
| Fssai License of Dalgreen, CP. 2027.pdf | `1rJfIbu27SObYTwwUmUHHCEYh70pswZ6e` | 2025-08-21 | Connaught Place FSSAI 13324009000420, issued 2024-10-16, valid to 2027-10-15 |
| NDMC HEALTHAND TRADE.pdf | `1LDYIj7XGQM9dRAwgrktjzpOI2fOjXIQc` | 2025-01-13 | Connaught Place NDMC health/trade 2024120517696, fee 13 Jan 2025, valid to 2027-03-31 |
| Fssai Renewal License For Dosa Coffee Kalkaji.pdf | `1PLR-XjJKCIAW6WJX1DL3o_cVkcAsXe18` | 2024-11-07 | Kalkaji FSSAI 13323010000701, 3-year renewal issued 2024-10-17, valid to 2027-10-24 |
| Fssai License For Dossa Coffee Okhla.pdf | `1PaWtHitdb54EWJGtsAOqaA0KaB4bMlSa` | 2024-03-20 | Okhla kitchen (Z-51, Phase II) FSSAI 13324010000165, issued 2024-03-11, valid to 2027-03-10 |
| PASCHIM VIHAR FSSAI LICENSE.pdf | `1IKWYdcSk8AKd3YUi6jlkKWs-IjuWCvHU` | 2023-09-14 | Only Paschim Vihar FSSAI on Drive; issued 2023-08-02, expired 2024-08-01. Not used as a current expiry. |
| New license.pdf | `1el5G6f7P4a7jFWYrxSIbTH_SW_2qQbU3` | 2025-11-13 | Original 2023-24 Sec 143 Noida issue, superseded by FSSAI 2026.pdf. |
| Expired Fssai License Of Gurgaon Sec - 15.pdf | `1eOcPfe6kn0xpseyRzk9-E7QfIIJV9hAy` | 2026-02-13 | Confirmed as an expired/old certificate; no current Gurgaon Sec-15 FSSAI found. |
| FSSAI Faridabad 2027.pdf | `1V4BJDKAXIVr-c_GVULblcb0dHepVlJ6g` | 2026-02-13 | Read only to confirm it is Faridabad Sec-15 (SCF-78, Sector 15 Market), FSSAI 10824003000072 valid to 2027-02-20. Closed store — not in the CSV. |

Kolkata FSSAI PDFs (Technopolis, Santoshpur, Behala/Jameslong, Rosedale, Lake Road, Kasba receipt, Laketown, Rangoli, Ideal Plaza / IP, Forum, Kalikapur, and related receipts) were listed in search and used only as corroboration that certificates exist; current Kolkata expiries and numbers come from the 16 Jul 2026 LICENSE sheet, which already carries the 14-digit FSSAI numbers.

Third-party or non-Dosa Coffee FSSAI files (Casa Italiana, AVA Greens, Indicannaco, Hima Shah, SHASIN Beverages, Toddler Foods, Meraki Cheese, GrandAgro, Mansi Kamdar, bg tea vyapar, and similar) were ignored.

## Does a current NCR tracker exist?

**A current NCR status tracker exists, but a current dated NCR expiry tracker does not.**

`Delhi NCR/ License Validity Date`, last edited by Sanjoy Roy on 22 May 2026, is the newest NCR workbook. It only records Yes / Pending / Not Available / WIP / N/A. It has no issue or expiry dates, and it predates three trading stores that appear in Sep 2026 Grand Economics: Shalimar Bagh, Gurgaon Sec 10 and Sec 31 Gurgaon.

The 2024 Abhishek "License Status" sheet is stale. The "Expired License Folder Delhi NCR" (modified 7 Aug 2026) only held older Model Town FSSAI PDFs when listed.

**Ask Sanjoy for the Drive location of:** a dated NCR licence-expiry tracker (if one exists after May 2026); the current Paschim Vihar and Gurgaon Sec-15 FSSAI certificates (tracker says Yes, Drive only has expired files); and the Chinar Park / The One Mall licence pack. Do not email him from this pass.

## Coverage gaps

### Closed stores (noted only, excluded from the CSV)

- **Chattarpur** — closed long ago; excluded from the sales base. Old FSSAI and labour PDFs exist (2024).
- **GK1 Cloud Kitchen** — closed long ago; no current licence pack reviewed.
- **Faridabad Sec-15** — closed 22/23 October 2026; excluded from the sales base. FSSAI 10824003000072 was renewed on 13 Feb 2026 and would have run to 20 Feb 2027 if the store were still open.

### Kolkata stores or types with no current data

- **Chinar Park** — in Sep 2026 Grand Economics, not on any licence tracker. The One Mall folder (`1PosvMb6vWKMu8XPW6KbAIp83UGnkdB68`, modified 14 Jul 2026) only has a rent agreement. No FSSAI, trade, fire or police file found under Chinar Park or The One Mall.
- **Food Truck - 1 (Technopolis)** — trade and FSSAI are dated; fire, police, metrology and shops are blank in the July sheet.
- **CK Kasba** — trading kitchen, not a cafe in the Sep 2026 P&L list. Fire is under process; PPL, metrology and shops are blank in the July sheet.
- **Kalikapur and CK Kasba fire** — "under process" (missing).
- Police applications still open or on hold: Manisquare, Quest Mall, Kalikapur, plus holds at Salt Lake Sec-1, Rosedale, New Town Cloud Kitchen, Rangoli Mall and Salt Lake Sec-3. Lake Town police was withdrawn (outside Kolkata Police jurisdiction).
- Shops & establishment: the July sheet often gives only an "Issued on …" remark and "valid for 3 years", with no explicit expiry, so status is `unknown`. Three issue dates are after 13 Nov 2026 (Salt Lake Sec-1 and Rosedale "18.12.2026", Quest Mall and New Town "16.12.2026"). The 12 Jan 2026 tab of the Legal License Update sheet had 18.12.2025 / 16.12.2025, so these may be year typos. Left as written, not corrected.
- Water-test reports: a folder `WATER TESTING REPORT_Oct26-Mar27` was modified 5 Oct 2026, but individual reports were not parsed into the table.
- Fresh Aisle Mart (Elgin, Kasba retail, head office) and group-company trade licences in the Kolkata workbooks were excluded as they are not Dosa Coffee stores.

### NCR stores or types with no current dated data

- **Paschim Vihar FSSAI** — May 2026 tracker says Yes; only Drive certificate expired 1 Aug 2024. Current certificate not found.
- **Gurgaon Sec-15 FSSAI** — same pattern: tracker says Yes; Drive only has an "Expired" file. Current certificate not found. Store is still in the sales base (not one of the three closed stores).
- **Shalimar Bagh, Gurgaon Sec 10, Sec 31 Gurgaon** — have current FSSAI certificates (and Shalimar Bagh has a health-trade licence) but are absent from the May 2026 tracker, so other licence types are marked missing.
- Almost all NCR MCD / DPCC / eating house / labour / fire NOC / water-test / weighing-scale / fire-cylinder rows have **no dates**. "Yes" on the May tracker is recorded as `unknown`, not `valid`.
- **Okhla** is the Z-51 central kitchen / office, not a Sep 2026 trading cafe. Included because it is on the May 2026 NCR tracker and has a current FSSAI.
- Fire NOC PDFs (CP, Okhla, Model Town image, Pacific / Jasola police packs, MCD PDFs for Okhla, Model Town, Pacific, Rohini, Kalkaji) were found, many from late 2024, often large or image-heavy. They were not fully mined for expiry dates in this pass; NCR fire / MCD rows therefore stay on the May 2026 tracker flags unless a text certificate already gave a date (Shalimar Bagh HTL, CP NDMC).

### Searches that did not yield a newer NCR expiry workbook

Queries included licence / license, FSSAI, trade license, fire NOC, shop and establishment, health trade, NCR license status, and folders named License or Compliance, including files modified since 2025. The May 2026 status sheet is the newest NCR workbook. No dated successor was found.

## Expired and expiring as of 13 November 2026

### Expired (9)

| Store | City | Type | Licence no. | Expiry | Note |
|---|---|---|---|---|---|
| Sec 143 Noida | NCR | FSSAI | 12723055001338 | 2026-11-12 | Expired the day before the as-of date. No 2026-27 certificate on Drive. |
| Forum | Kolkata | Police | PS/SD/T1/1322/2022 | 2026-03-31 | Renewal applied 22 Apr 2026; revert still pending fire NOC from the mall as of 9 Jun 2026. |
| New Town Cloud Kitchen | Kolkata | Fire NOC |  | 2026-07-16 |  |
| Salt Lake Sec-1 | Kolkata | Fire NOC |  | 2026-08-01 |  |
| Salt Lake Sec-3 | Kolkata | Fire NOC |  | 2026-09-10 |  |
| Rangoli Mall | Kolkata | PPL | 2023/114628/1/1 | 2026-08-31 |  |
| Lake Road | Kolkata | PPL | 2024/152806/1/1 | 2026-09-20 |  |
| James Long Sarani | Kolkata | PPL | 2023/119303/1/1 | 2026-10-09 |  |
| Santoshpur | Kolkata | PPL | 2023/120650/1/1 | 2026-10-24 |  |

### Expiring within 30 days (3)

| Store | City | Type | Licence no. | Expiry |
|---|---|---|---|---|
| Ideal Plaza | Kolkata | PPL | 2023/124326/2/1 | 2026-12-04 |
| Lake Town | Kolkata | PPL | 2023/124326/1/1 | 2026-12-04 |
| Gurgaon Sec 10 | NCR | FSSAI | 10825005002315 | 2026-12-11 |

### Expiring within 90 days (31–90 days)

None. The closest valid licence just outside the window is Shalimar Bagh FSSAI, expiry 2027-02-16 (95 days).

## Method notes

- Kolkata trade, FSSAI, fire, PPL, police and metrology expiries are taken from the 16 Jul 2026 LICENSE sheet unless a later certificate contradicted them (none did).
- Scientific-notation corruption in the xlsx exports (for example `1.2819019002029E13`) was avoided by using the LICENSE sheet's 14-digit FSSAI numbers.
- Excel serial dates in the older xlsx (for example `45083`) were not used as current expiries.
- Scanned or image PDFs: the FSSAI Form C files and the Shalimar Bagh / NDMC health-trade PDFs had a readable text layer via Drive `read_file`. Large late-2024 MCD and Delhi Police packs were not fully extracted; if a future pass needs those dates, download and run `pdftotext`, and note any file with no text layer.
