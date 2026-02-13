from datetime import datetime
def today_ddmmyyyy():
    return datetime.now().strftime("%d.%m.%Y")