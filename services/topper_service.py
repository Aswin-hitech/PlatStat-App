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


def _normalize_df_columns(df):
    rename_dict = {}
    for col in df.columns:
        c_str = str(col).strip().lower().replace("_", " ").replace(".", "")
        if c_str in ("name", "student name", "studentname", "name of student", "name of the student"):
            rename_dict[col] = "Name of the Student"
        elif c_str in ("date", "contest date", "fetch date"):
            rename_dict[col] = "Date"
        elif c_str in ("contest rating", "contestrating", "lc rating", "leetcode rating"):
            rename_dict[col] = "Contest Rating"
        elif c_str in ("current rating", "currentrating", "cf rating", "codeforces rating", "cc rating", "codechef rating", "rating"):
            rename_dict[col] = "Current Rating"
    return df.rename(columns=rename_dict)


def clean_excel(df):
    df = _normalize_df_columns(df)
    if "Name of the Student" in df.columns:
        return df.dropna(how="all").reset_index(drop=True)

    expected_header = ["S. No", "Name of the Student", "Date"]
    header_rows = []

    for i in range(len(df)):
        values = [str(x).strip() for x in df.iloc[i].values]
        if any("Name" in str(x) for x in values) and any("Date" in str(x) or "Rating" in str(x) for x in values):
            header_rows.append(i)

    if not header_rows:
        return df

    tables = []
    for idx, start in enumerate(header_rows):
        end = header_rows[idx + 1] if idx + 1 < len(header_rows) else len(df)
        table = df.iloc[start:end].copy()
        table.columns = table.iloc[0]
        table = table[1:].dropna(how="all")
        table = _normalize_df_columns(table)
        if "Name of the Student" in table.columns:
            table = table[table["Name of the Student"] != "Name of the Student"]
        tables.append(table)

    if not tables:
        return df

    return pd.concat(tables, ignore_index=True).reset_index(drop=True)


def compute_topper(df, platform, month):
    platform = (platform or "").strip().lower()
    rating_column = RATING_COLUMNS.get(platform)
    if not rating_column:
        return pd.DataFrame()

    df = clean_excel(df)
    df = _normalize_df_columns(df)
    df = filter_month(df, month)

    if df.empty or "Name of the Student" not in df.columns:
        return pd.DataFrame()

    if rating_column not in df.columns:
        # Fallback to any rating column present
        candidates = [c for c in ("Contest Rating", "Current Rating", "Rating") if c in df.columns]
        if candidates:
            rating_column = candidates[0]
        else:
            return pd.DataFrame()

    df = df.copy()
    df[rating_column] = df[rating_column].apply(to_int)
    df = df.dropna(subset=["Name of the Student"])
    # Filter out records where rating couldn't be parsed
    df = df[df[rating_column].notna()]

    if df.empty:
        return pd.DataFrame()

    grouped = (
        df.groupby("Name of the Student", as_index=False)
        .agg({rating_column: "max"})
        .sort_values(by=[rating_column, "Name of the Student"], ascending=[False, True])
        .reset_index(drop=True)
    )
    return grouped

