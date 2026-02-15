import pandas as pd
import numpy as np


# =====================================================
# UNIVERSAL SAFE PARSERS
# =====================================================

def to_int(x):
    if pd.isna(x):
        return None
    x = str(x).strip()
    if x in ["AB", "-", ""]:
        return None
    try:
        return int(float(x))
    except:
        return None


def parse_date_column(df):
    if "Date" not in df.columns:
        return df

    df = df.copy()
    df["Date"] = pd.to_datetime(
        df["Date"],
        dayfirst=True,
        errors="coerce"
    )
    return df


def filter_month(df, month):
    df = parse_date_column(df)
    if "Date" not in df.columns:
        return pd.DataFrame()
    return df[df["Date"].dt.month == month]


# =====================================================
# MULTI TABLE DETECTOR (ROBUST)
# =====================================================

EXPECTED_HEADER = [
    "S. No",
    "Name of the Student",
    "Date"
]

def is_header_row(row):
    values = [str(x).strip() for x in row.values]
    return all(h in values for h in EXPECTED_HEADER)


def clean_excel(df):

    # Case 1: already clean
    if "Name of the Student" in df.columns:
        return df.dropna(how="all").reset_index(drop=True)

    tables = []
    header_positions = []

    # find header rows
    for i in range(len(df)):
        if is_header_row(df.iloc[i]):
            header_positions.append(i)

    if not header_positions:
        return pd.DataFrame()

    # slice tables
    for idx, start in enumerate(header_positions):
        end = header_positions[idx+1] if idx+1 < len(header_positions) else len(df)

        table = df.iloc[start:end].copy()
        table.columns = table.iloc[0]
        table = table[1:]
        table = table.dropna(how="all")

        # remove rows that accidentally contain header again
        table = table[table["Name of the Student"] != "Name of the Student"]

        tables.append(table)

    merged = pd.concat(tables, ignore_index=True)
    return merged.reset_index(drop=True)


# =====================================================
# LEETCODE TOPPER
# =====================================================

def topper_leetcode(df, month):

    df = clean_excel(df)
    df = filter_month(df, month)
    if df.empty:
        return pd.DataFrame()

    df["Total(No.of Problem Solved)"] = df["Total(No.of Problem Solved)"].apply(to_int)
    df["Contest Rating"] = df["Contest Rating"].apply(to_int)
    df["Global Rank"] = df["Global Rank"].apply(to_int)

    grouped = df.groupby("Name of the Student").agg({
        "Total(No.of Problem Solved)": "sum",
        "Contest Rating": "max",
        "Global Rank": "min"
    }).reset_index()

    grouped = grouped.sort_values(
        by=["Total(No.of Problem Solved)", "Contest Rating", "Global Rank"],
        ascending=[False, False, True]
    )

    return grouped.head(5)


# =====================================================
# CODEFORCES TOPPER
# =====================================================

def topper_codeforces(df, month):

    df = clean_excel(df)
    df = filter_month(df, month)
    if df.empty:
        return pd.DataFrame()

    df["Problem Solved"] = df["Problem Solved"].apply(to_int)
    df["Current Rating"] = df["Current Rating"].apply(to_int)
    df["Current Rank"] = df["Current Rank"].apply(to_int)

    grouped = df.groupby("Name of the Student").agg({
        "Problem Solved": "sum",
        "Current Rating": "max",
        "Current Rank": "min"
    }).reset_index()

    grouped = grouped.sort_values(
        by=["Problem Solved", "Current Rating", "Current Rank"],
        ascending=[False, False, True]
    )

    return grouped.head(5)


# =====================================================
# CODECHEF TOPPER
# =====================================================

def topper_codechef(df, month):

    df = clean_excel(df)
    df = filter_month(df, month)
    if df.empty:
        return pd.DataFrame()

    df["Current Rating"] = df["Current Rating"].apply(to_int)
    df["Global ranking"] = df["Global ranking"].apply(to_int)

    grouped = df.groupby("Name of the Student").agg({
        "Current Rating": "max",
        "Global ranking": "min"
    }).reset_index()

    grouped = grouped.sort_values(
        by=["Current Rating", "Global ranking"],
        ascending=[False, True]
    )

    return grouped.head(5)


# =====================================================
# UNIVERSAL WRAPPER
# =====================================================

def compute_topper(df, platform, month):

    if platform == "leetcode":
        return topper_leetcode(df, month)

    elif platform == "codeforces":
        return topper_codeforces(df, month)

    elif platform == "codechef":
        return topper_codechef(df, month)

    return pd.DataFrame()
