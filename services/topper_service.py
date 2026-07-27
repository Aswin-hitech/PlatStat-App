import pandas as pd


RATING_COLUMNS = {
    "leetcode": "Contest Rating",
    "codeforces": "Current Rating",
    "codechef": "Current Rating",
}


def to_int(value):
    if pd.isna(value):
        return None
    text = str(value).strip()
    if text in ("", "AB", "-"):
        return None
    try:
        return int(float(text))
    except Exception:
        return None


def parse_date_column(df):
    if "Date" not in df.columns:
        return df

    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    return df


def filter_month(df, month):
    df = parse_date_column(df)
    if "Date" not in df.columns:
        return pd.DataFrame()
    return df[df["Date"].dt.month == month]


def clean_excel(df):
    if "Name of the Student" in df.columns:
        return df.dropna(how="all").reset_index(drop=True)

    expected_header = ["S. No", "Name of the Student", "Date"]
    header_rows = []

    for i in range(len(df)):
        values = [str(x).strip() for x in df.iloc[i].values]
        if all(h in values for h in expected_header):
            header_rows.append(i)

    if not header_rows:
        return pd.DataFrame()

    tables = []
    for idx, start in enumerate(header_rows):
        end = header_rows[idx + 1] if idx + 1 < len(header_rows) else len(df)
        table = df.iloc[start:end].copy()
        table.columns = table.iloc[0]
        table = table[1:].dropna(how="all")
        if "Name of the Student" in table.columns:
            table = table[table["Name of the Student"] != "Name of the Student"]
        tables.append(table)

    return pd.concat(tables, ignore_index=True).reset_index(drop=True)


def compute_topper(df, platform, month):
    platform = (platform or "").strip().lower()
    rating_column = RATING_COLUMNS.get(platform)
    if not rating_column:
        return pd.DataFrame()

    df = clean_excel(df)
    df = filter_month(df, month)
    if df.empty or "Name of the Student" not in df.columns or rating_column not in df.columns:
        return pd.DataFrame()

    df = df.copy()
    df[rating_column] = df[rating_column].apply(to_int)
    df = df.dropna(subset=["Name of the Student"])

    grouped = (
        df.groupby("Name of the Student", as_index=False)
        .agg({rating_column: "max"})
        .sort_values(by=[rating_column, "Name of the Student"], ascending=[False, True])
        .reset_index(drop=True)
    )
    return grouped
