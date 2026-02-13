import pandas as pd
import os
from datetime import datetime


def build_excel(cf, cc, lc):
    # Create Output folder if it doesn't exist
    output_dir = "Output"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # Generate filename with current date (DDMMYYYY_Tracked.xlsx)
    current_date = datetime.now().strftime("%d%m%Y")
    filename = f"{current_date}_Tracked.xlsx"
    file_path = os.path.join(output_dir, filename)

    # One sheet — three tables stacked
    start = 0
    with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
        sheet = "Report"

        if cc:
            df = pd.DataFrame(cc)
            df.to_excel(writer, sheet_name=sheet, startrow=start, index=False)
            start += len(df) + 3

        if lc:
            df = pd.DataFrame(lc)
            df.to_excel(writer, sheet_name=sheet, startrow=start, index=False)
            start += len(df) + 3

        if cf:
            df = pd.DataFrame(cf)
            df.to_excel(writer, sheet_name=sheet, startrow=start, index=False)

    return file_path

