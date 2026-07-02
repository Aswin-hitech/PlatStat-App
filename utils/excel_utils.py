import pandas as pd
from io import BytesIO

def create_excel_file(data_frames, sheet_names):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        for df, sheet_name in zip(data_frames, sheet_names):
            df.to_excel(writer, sheet_name=sheet_name, index=False)
    output.seek(0)
    return output

def read_excel_file(file_stream):
    return pd.read_excel(file_stream)
