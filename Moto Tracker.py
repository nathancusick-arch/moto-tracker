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


def tracker_col_from_date(ts: pd.Timestamp, token_class: str) -> str:
    """Map date + token into an exact tracker column label."""
    month_name = ts.strftime("%B")
    year_short = ts.strftime("%y")
    base = f"{month_name} '{year_short}"
    return base if token_class == "monthly" else base + " Extra"


# ---------------------------------------------------------
# STREAMLIT FILE UPLOADER
# ---------------------------------------------------------

uploaded_file = st.file_uploader("Upload audits_basic_data_export.csv", type=["csv"])

if uploaded_file is not None:

    # Load CSV
    df = pd.read_csv(uploaded_file)

    # Only include completed audits
    df["status_norm"] = df.get("status").astype(str).str.strip().str.lower()
    df = df[df["status_norm"] == "approved"].copy()

    # UK dd/mm/yyyy
    df["date_of_visit"] = pd.to_datetime(df["date_of_visit"], dayfirst=True, errors="coerce")
    df = df[df["date_of_visit"].notna()].copy()

    # Parse time_of_visit for tie-breaks (missing times treated as 00:00:00)
    df["time_of_visit_td"] = pd.to_timedelta(df.get("time_of_visit"), errors="coerce").fillna(pd.Timedelta(0))
    df["visit_dt"] = df["date_of_visit"] + df["time_of_visit_td"]

    df["PRIMARY_RESULT"] = df["primary_result"].astype(str).str.upper()
    df["token_class"] = df["tokens"].astype(str).str.strip().str.lower()

    # Decide which tracker column each visit goes into:
    # - Base column contains exactly 1 visit per site+month: the earliest Monthly/Weekly audit
    # - All other approved Monthly/Weekly go to Extra
    # - Random audits go to Extra, EXCEPT if there are no Monthly/Weekly that month for that site (then earliest Random goes to base)
    df["col_year"] = df["date_of_visit"].dt.year
    df["col_month"] = df["date_of_visit"].dt.month

    def _month_base_label(ts: pd.Timestamp) -> str:
        month_name = ts.strftime("%B")
        year_short = ts.strftime("%y")
        return f"{month_name} '{year_short}"

    df["month_base"] = df["date_of_visit"].apply(_month_base_label)

    def _token_group(tok: str) -> str:
        if tok in {"monthly", "weekly"}:
            return "mw"
        if tok == "random":
            return "random"
        return "other"

    df["token_group"] = df["token_class"].apply(_token_group)

    df = df.sort_values(["site_internal_id", "col_year", "col_month", "visit_dt"])

    # Assign base vs extra per site+month
    # Rule:
    # - Base column contains exactly 1 audit per site+month:
    #     - Prefer the earliest Monthly/Weekly audit that is NOT emergency.
    #     - Emergency Monthly/Weekly audits go to Extra unless:
    #         * it is the only Monthly/Weekly audit in that month, OR
    #         * all Monthly/Weekly audits that month are emergency (then earliest emergency goes to base).
    #     - If there are no Monthly/Weekly audits, the earliest Random goes to base (if any).
    df["is_base"] = False

    # Ensure order_schedule_type exists
    if "order_schedule_type" not in df.columns:
        df["order_schedule_type"] = ""

    df["order_schedule_type_norm"] = df["order_schedule_type"].fillna("").astype(str).str.strip().str.lower()

    for (site, y, mth), g in df.groupby(["site_internal_id", "col_year", "col_month"], sort=False):
        base_idx = None

        g_mw = g[g["token_group"] == "mw"]
        if len(g_mw) > 0:
            if len(g_mw) == 1:
                # Only one Monthly/Weekly audit: it becomes base even if emergency
                base_idx = g_mw["visit_dt"].idxmin()
            else:
                # Multiple Monthly/Weekly audits: prefer earliest non-emergency
                g_non_em = g_mw[g_mw["order_schedule_type_norm"] != "emergency"]
                if len(g_non_em) > 0:
                    base_idx = g_non_em["visit_dt"].idxmin()
                else:
                    # All Monthly/Weekly audits are emergency: earliest emergency becomes base
                    base_idx = g_mw["visit_dt"].idxmin()
        else:
            # No Monthly/Weekly audits: earliest Random becomes base (if any)
            g_rand = g[g["token_group"] == "random"]
            base_idx = g_rand["visit_dt"].idxmin() if len(g_rand) > 0 else None

        if base_idx is not None:
            df.loc[base_idx, "is_base"] = True

    df["tracker_column"] = df["month_base"] + df["is_base"].map(lambda b: "" if b else " Extra")

    # Chronological order for merging
    df["col_year"] = df["date_of_visit"].dt.year
    df["col_month"] = df["date_of_visit"].dt.month
    df = df.sort_values(["site_internal_id", "visit_dt"])

    # Build dynamic column list based on dates present
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
        site = str(row["site_internal_id"])
        col = row["tracker_column"]

        if site not in out.index or col not in out.columns:
            continue

        day_str = day_ordinal(row["date_of_visit"])
        val = f"{row['PRIMARY_RESULT']} - {day_str}"

        existing = out.loc[site, col]
        out.loc[site, col] = val if pd.isna(existing) or existing == "" else f"{existing}, {val}"

    # Fill N/A for past months
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
