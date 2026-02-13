import pandas as pd

def parse_csv(file):
    df = pd.read_csv(file)
    return df.to_dict(orient="records")