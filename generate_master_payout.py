import os
import pandas as pd
import uuid

def process_uploaded_files(file_paths, output_folder):
    columns = [
        "(B) Service Fee  & Payment Mechanism Fee",
        "(13) Taxes on Service & Payment Mechanism Fees (B) * 18%",
        "(18) TDS 194O amount",
        "(19) GST paid by Zomato on behalf of restaurant - under section 9(5)",
        "Order Level Payout  (A) - (E) + (F)",
        "Restaurant ID",
        "A) Investments in growth services Adjusted Amount",
        "B) Investment in Hyperpure"
    ]

    master_data = []
    report_period_value = "UNKNOWN"
    report_period_found = False
    logs = []

    for file in file_paths:
        logs.append(f"📄 Processing: {os.path.basename(file)}")

        try:
            order_df = pd.read_excel(file, sheet_name="Order Level", header=None)
            deductions_df = pd.read_excel(file, sheet_name="Addition Deductions Details", header=None)

            if not report_period_found:
                try:
                    summary_df = pd.read_excel(file, sheet_name="Summary", header=None)
                    for i in range(len(summary_df)):
                        cell_value = str(summary_df.iloc[i, 0]).strip().lower()
                        if "report period" in cell_value:
                            report_period_value = str(summary_df.iloc[i, 1]).strip().replace(" ", "_").replace("/", "_")
                            report_period_found = True
                            logs.append(f"🟢 Report period extracted: {report_period_value}")
                            break
                except Exception as e:
                    logs.append(f"⚠️ Could not extract 'Report Period': {e}")

            header_candidates = order_df[order_df.astype(str).apply(lambda row: row.str.contains("S.No.", na=False)).any(axis=1)]
            if header_candidates.empty:
                logs.append("🔴 Skipped: No 'S.No.' row found")
                continue

            header_row_index = header_candidates.index[0]
            order_df.columns = order_df.iloc[header_row_index]
            order_df = order_df[header_row_index + 1:]

            required_cols = [
                "Service fee & payment mechanism fees\n[(11) + (12)]",
                "Taxes on service & payment mechanism fees\n(B) * 18%",
                "TDS 194O amount",
                "Order level Payout\n(A) - (E) + (F)",
                "Res. ID"
            ]
            # We will check GST column separately due to flexible name
            missing = [col for col in required_cols if col not in order_df.columns]
            if missing:
                logs.append(f"🔴 Skipped: Missing columns {missing}")
                continue

            def safe_sum(col):
                return pd.to_numeric(order_df[col], errors='coerce').sum()

            # Find GST column flexibly
            gst_cols = [col for col in order_df.columns if "gst paid by zomato" in str(col).lower()]
            if gst_cols:
                gst_col = gst_cols[0]
            else:
                logs.append("⚠️ GST column with 'GST paid by Zomato' not found, defaulting to 0")
                gst_col = None

            row = {
                "(B) Service Fee  & Payment Mechanism Fee": safe_sum("Service fee & payment mechanism fees\n[(11) + (12)]"),
                "(13) Taxes on Service & Payment Mechanism Fees (B) * 18%": safe_sum("Taxes on service & payment mechanism fees\n(B) * 18%"),
                "(18) TDS 194O amount": safe_sum("TDS 194O amount"),
                "(19) GST paid by Zomato on behalf of restaurant - under section 9(5)": max(0, safe_sum(gst_col)) if gst_col else 0,
                "Order Level Payout  (A) - (E) + (F)": safe_sum("Order level Payout\n(A) - (E) + (F)")
            }

            rest_id_series = order_df["Res. ID"].dropna()
            row["Restaurant ID"] = rest_id_series.iloc[0] if not rest_id_series.empty else "UNKNOWN"

            header_row_ded = deductions_df[deductions_df.astype(str).apply(lambda r: r.str.contains("Adjusted amount", na=False)).any(axis=1)]
            if not header_row_ded.empty:
                header_index = header_row_ded.index[0]
                deductions_df.columns = deductions_df.iloc[header_index]
                deductions_df = deductions_df[header_index + 1:]
            else:
                deductions_df = pd.DataFrame(columns=["Type", "Adjusted amount"])

            def extract_adjusted(label):
                if "Type" not in deductions_df.columns or "Adjusted amount" not in deductions_df.columns:
                    return 0
                match = deductions_df[deductions_df["Type"].astype(str).str.contains(label, na=False)]
                return pd.to_numeric(match["Adjusted amount"], errors="coerce").sum() if not match.empty else 0

            row["A) Investments in growth services Adjusted Amount"] = extract_adjusted("Total Ads & miscellaneous services")
            row["B) Investment in Hyperpure"] = extract_adjusted("Total Hyperpure")

            master_data.append(row)
            logs.append(f"✅ Done: {os.path.basename(file)}")

        except Exception as e:
            logs.append(f"❌ Error: {file} → {e}")

    if master_data:
        master_df = pd.DataFrame(master_data, columns=columns)
        output_filename = f"Dosa_Coffee_Master_output_Report_Period_{report_period_value}.xlsx"
        output_path = os.path.join(output_folder, output_filename)
        master_df.to_excel(output_path, index=False)
        logs.append(f"✅ File ready: {output_path}")
        return output_path, logs
    else:
        logs.append("⚠️ No valid data found to export.")
        return None, logs
