import pandas as pd
from io import BytesIO
from datetime import datetime


def build_excel(cf, cc, lc):

    output = BytesIO()
    start = 0

    with pd.ExcelWriter(output, engine="openpyxl") as writer:

        sheet = "Report"

        # ---------------- CodeChef ----------------
        if cc:
            df = pd.DataFrame(cc)
            df.to_excel(
                writer,
                sheet_name=sheet,
                startrow=start,
                index=False
            )
            start += len(df) + 3

        # ---------------- LeetCode ----------------
        if lc:
            df = pd.DataFrame(lc)
            df.to_excel(
                writer,
                sheet_name=sheet,
                startrow=start,
                index=False
            )
            start += len(df) + 3

        # ---------------- Codeforces ----------------
        if cf:
            df = pd.DataFrame(cf)
            df.to_excel(
                writer,
                sheet_name=sheet,
                startrow=start,
                index=False
            )

    output.seek(0)
    return output
