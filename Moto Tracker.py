import streamlit as st
import pandas as pd
import io
from datetime import datetime

st.title("Moto Audit Tracker Mapper")

st.write("""
          1. Export full month(s) of Moto data
          2. Drop the file in the below box, it should then give you the output file in your downloads
          3. Paste into the Moto Tracker
          4. Done.
          """)

# ---------------------------------------------------------
# EXACT SITE ORDER FROM TRACKER
# ---------------------------------------------------------

TRACKER_SITE_ORDER = [
    "SITE32718", "SITE32719", "SITE32720", "SITE32721", "SITE32722",
    "SITE32723", "SITE32724", "SITE32725", "SITE32727", "SITE32728",
    "SITE32729", "SITE32730", "SITE32731", "SITE32732", "SITE32733",
    "SITE32734", "SITE32736", "SITE32737", "SITE32738", "SITE32739",
    "SITE32740", "SITE32741", "SITE32742", "SITE32743", "SITE32744",
    "SITE32745", "SITE32746", "SITE32747", "SITE32748", "SITE32749",
    "SITE32750", "SITE32751", "SITE32752", "SITE32753", "SITE32754",
    "SITE32755", "SITE32756", "SITE32757", "SITE32758", "SITE32759",
    "SITE32760", "SITE32761", "SITE32762", "SITE32763", "SITE32764",
    "SITE32765", "SITE32767", "SITE32768", "SITE32769", "SITE32771",
    "SITE32772", "SITE32773", "SITE48318", "SITE306813",
]


# ---------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------

def day_ordinal(ts: pd.Timestamp) -> str:
    d = ts.day
    if 11 <= d <= 13:
        suffix = "TH"
    else:
        suffix = {1: "ST", 2: "ND", 3: "RD"}.get(d % 10, "TH")
    return f"{d}{suffix}"


def _month_base_label(ts: pd.Timestamp) -> str:
    month_name = ts.strftime("%B")
    year_short = ts.strftime("%y")
    return f"{month_name} '{year_short}"


def _token_group(tok: str) -> str:
    if tok in {"monthly", "weekly"}:
        return "mw"
    if tok == "random":
        return "random"
    return "other"


# ---------------------------------------------------------
# STREAMLIT FILE UPLOADER
# ---------------------------------------------------------

uploaded_file = st.file_uploader("Upload audits_basic_data_export.csv", type=["csv"])

if uploaded_file is not None:
    # Load CSV
    df = pd.read_csv(uploaded_file)

    # Keep everything except deleted
    df["status_norm"] = df.get("status").astype(str).str.strip().str.lower()
    df = df[df["status_norm"] != "deleted"].copy()

    # Approved vs non-approved
    df["is_approved"] = df["status_norm"] == "approved"

    # Parse dates (UK dd/mm/yyyy). Month assignment:
    # - Approved: month from date_of_visit
    # - Non-approved: month from start_date
    df["date_of_visit_dt"] = pd.to_datetime(df.get("date_of_visit"), dayfirst=True, errors="coerce")
    df["start_date_dt"] = pd.to_datetime(df.get("start_date"), dayfirst=True, errors="coerce")

    df["month_dt"] = df["date_of_visit_dt"].where(df["is_approved"], df["start_date_dt"])
    df = df[df["month_dt"].notna()].copy()

    # Parse time_of_visit for approved tie-breaks (missing times treated as 00:00:00)
    df["time_of_visit_td"] = pd.to_timedelta(df.get("time_of_visit"), errors="coerce").fillna(pd.Timedelta(0))
    df["visit_dt"] = df["date_of_visit_dt"] + df["time_of_visit_td"]

    # Normalized fields
    df["PRIMARY_RESULT"] = df.get("primary_result").astype(str).str.upper()
    df["token_class"] = df.get("tokens").astype(str).str.strip().str.lower()
    df["token_group"] = df["token_class"].apply(_token_group)

    # Ensure order_schedule_type exists
    if "order_schedule_type" not in df.columns:
        df["order_schedule_type"] = ""
    df["order_schedule_type_norm"] = df["order_schedule_type"].fillna("").astype(str).str.strip().str.lower()

    # Grouping keys by month (based on month_dt)
    df["col_year"] = df["month_dt"].dt.year
    df["col_month"] = df["month_dt"].dt.month
    df["month_base"] = df["month_dt"].apply(_month_base_label)

    # Sort so "earliest" approved uses actual visit datetime; non-approved don't need strict chronology,
    # but we still sort deterministically.
    # Approved priority is enforced in the base-selection logic below.
    df = df.sort_values(
        ["site_internal_id", "col_year", "col_month", "is_approved", "visit_dt", "month_dt"],
        ascending=[True, True, True, False, True, True],
    )

    # ---------------------------------------------------------
    # Assign base vs extra per site+month
    #
    # Rules (as defined):
    # - Base column contains exactly 1 audit per site+month.
    # - Monthly/Weekly audits are preferred for base; approved takes priority over non-approved.
    # - Emergency audits go to Extra unless it is the ONLY Monthly/Weekly audit that month
    #   (or if multiple and all are emergency, earliest emergency becomes base).
    # - Random audits go to Extra, EXCEPT if there are no Monthly/Weekly audits that month for that site
    #   (then earliest Random goes to base). Approved Random takes priority over non-approved Random.
    #
    # - Cell text:
    #   - Approved: "RESULT - 4TH"
    #   - Non-approved: "TBC"
    # ---------------------------------------------------------
    df["is_base"] = False

    def _idxmin_dt(series: pd.Series) -> int:
        """Pick idx of earliest datetime, handling all-NaT."""
        s = pd.to_datetime(series, errors="coerce")
        if s.notna().any():
            return s.idxmin()
        # Fallback deterministic: first index
        return s.index[0]

    for (site, y, mth), g in df.groupby(["site_internal_id", "col_year", "col_month"], sort=False):
        base_idx = None

        g_mw = g[g["token_group"] == "mw"]
        g_mw_approved = g_mw[g_mw["is_approved"]]
        g_mw_nonapproved = g_mw[~g_mw["is_approved"]]

        # 1) Monthly/Weekly takes priority (approved preferred)
        if len(g_mw_approved) > 0:
            if len(g_mw_approved) == 1:
                # Only one approved MW: becomes base even if emergency
                base_idx = _idxmin_dt(g_mw_approved["visit_dt"])
            else:
                # Multiple approved MW: prefer earliest non-emergency
                g_non_em = g_mw_approved[g_mw_approved["order_schedule_type_norm"] != "emergency"]
                if len(g_non_em) > 0:
                    base_idx = _idxmin_dt(g_non_em["visit_dt"])
                else:
                    # All approved MW are emergency: earliest emergency becomes base
                    base_idx = _idxmin_dt(g_mw_approved["visit_dt"])

        elif len(g_mw_nonapproved) > 0:
            # No approved MW: choose among non-approved MW (month_dt only; no time ordering required)
            if len(g_mw_nonapproved) == 1:
                base_idx = _idxmin_dt(g_mw_nonapproved["month_dt"])
            else:
                g_non_em = g_mw_nonapproved[g_mw_nonapproved["order_schedule_type_norm"] != "emergency"]
                if len(g_non_em) > 0:
                    base_idx = _idxmin_dt(g_non_em["month_dt"])
                else:
                    base_idx = _idxmin_dt(g_mw_nonapproved["month_dt"])

        else:
            # 2) No Monthly/Weekly: earliest Random becomes base (approved preferred)
            g_rand = g[g["token_group"] == "random"]
            g_rand_approved = g_rand[g_rand["is_approved"]]
            g_rand_nonapproved = g_rand[~g_rand["is_approved"]]

            if len(g_rand_approved) > 0:
                base_idx = _idxmin_dt(g_rand_approved["visit_dt"])
            elif len(g_rand_nonapproved) > 0:
                base_idx = _idxmin_dt(g_rand_nonapproved["month_dt"])
            else:
                base_idx = None

        if base_idx is not None:
            df.loc[base_idx, "is_base"] = True

    df["tracker_column"] = df["month_base"] + df["is_base"].map(lambda b: "" if b else " Extra")

    # Chronological order for merging output strings (approved use visit_dt, non-approved use month_dt)
    df["sort_dt"] = df["visit_dt"].where(df["is_approved"], df["month_dt"])
    df = df.sort_values(["site_internal_id", "col_year", "col_month", "tracker_column", "sort_dt"])

    # Build dynamic column list based on months present (from month_dt)
    date_groups = (
        df[["col_year", "col_month"]]
        .drop_duplicates()
        .sort_values(["col_year", "col_month"])
        .to_records(index=False)
    )

    final_columns = []
    for y, m in date_groups:
        month_name = pd.to_datetime(f"{y}-{m}-01").strftime("%B")
        year_short = str(y)[-2:]
        base = f"{month_name} '{year_short}"
        final_columns.append(base)
        final_columns.append(base + " Extra")

    # Empty output table with correct site order
    out = pd.DataFrame(index=TRACKER_SITE_ORDER, columns=final_columns)
    out.index.name = "Site Code"

    # Fill table
    for _, row in df.iterrows():
        site = str(row.get("site_internal_id"))
        col = row.get("tracker_column")

        if site not in out.index or col not in out.columns:
            continue

        if bool(row.get("is_approved")):
            # Approved: show result + visit day
            if pd.isna(row.get("date_of_visit_dt")):
                # Safety fallback (shouldn't happen for approved since month_dt came from date_of_visit_dt)
                val = str(row.get("PRIMARY_RESULT", "")).strip() or "TBC"
            else:
                day_str = day_ordinal(row["date_of_visit_dt"])
                val = f"{row['PRIMARY_RESULT']} - {day_str}"
        else:
            # Non-approved: always TBC
            val = "TBC"

        existing = out.loc[site, col]
        out.loc[site, col] = val if pd.isna(existing) or existing == "" else f"{existing}, {val}"

    # Fill N/A for past months (months before current calendar month)
    today = datetime.today()
    current_y = int(today.strftime("%y"))
    current_m = int(today.strftime("%m"))

    for col in out.columns:
        parts = col.replace(" Extra", "").split(" '")
        month_name = parts[0]
        year_short = int(parts[1])
        month_num = pd.to_datetime(month_name, format="%B").month

        # Month is before current → fill N/A
        if (year_short < current_y) or (year_short == current_y and month_num < current_m):
            out[col] = out[col].fillna("N/A")

    # Preview
    st.subheader("Preview of Output")
    st.dataframe(out)

    # Prepare download
    buffer = io.BytesIO()
    out.to_csv(buffer, encoding="utf-8-sig")
    buffer.seek(0)

    st.download_button(
        label="Download Moto Tracker Results CSV",
        data=buffer,
        file_name="Moto Tracker Results.csv",
        mime="text/csv"
    )
