# Tally day book (owner-only)
daybook_vouchers.csv: every voucher parsed from the Tally Day Book exports for the four companies (Kolkata, Delhi, Haryana, UP), 30 Sep to 5 Nov 2026, deduplicated. Columns: company, date (dd-Mon-yy), type (voucher type), no, dr (debit ledger), cr (first credit ledger), amt (INR), source file.
Days covered: Delhi 24, Haryana 19, Kolkata 25, UP 20 of the 37 days; the other days are PDF-only or not received yet. Nothing after 5 Nov yet.
pnl_sep2026.csv and pnl_sep2026_ledger_map.csv: September 2026 P&L built from the trial balances, and the ledger-to-P&L line map.

Updated in the April 2026 history PR: parsed the raw Day Book packs already on the box for 16–27 Oct (single-day extracts, including later pages the original 16 Oct load missed) and 6–11 Nov (voucher dates 6, 8, 9 and 11 Nov only; 7 and 10 Nov are not in the pack). Bank statements in those folders were not loaded as Tally vouchers. Missing days are left out, not filled with zero. Dedup is by company, date, type, and voucher no.
