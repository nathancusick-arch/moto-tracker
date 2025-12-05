import streamlit as st
import pandas as pd
import io
from datetime import datetime

st.title("Moto Audit Tracker Mapper")

st.write("""
          1. Export full month of Moto data
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

    # UK dd/mm/yyyy
    df["date_of_visit"] = pd.to_datetime(df["date_of_visit"], dayfirst=True, errors="coerce")
    df = df[df["date_of_visit"].notna()].copy()

    df["PRIMARY_RESULT"] = df["primary_result"].astype(str).str.upper()
    df["token_class"] = df["tokens"].astype(str).str.strip().str.lower()

    # Determine exact column headers
    df["tracker_column"] = df.apply(
        lambda r: tracker_col_from_date(r["date_of_visit"], r["token_class"]),
        axis=1
    )

    # Chronological order for merging
    df["col_year"] = df["date_of_visit"].dt.year
    df["col_month"] = df["date_of_visit"].dt.month
    df = df.sort_values(["site_internal_id", "date_of_visit"])

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
