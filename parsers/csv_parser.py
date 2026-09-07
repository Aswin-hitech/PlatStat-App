import pandas as pd

def parse_csv(file):
    df = pd.read_csv(file)
    df = df.fillna("")
    return df.to_dict(orient="records")