from datetime import datetime


def week_key(dt):
    dt = dt or datetime.utcnow()
    return f"{dt.isocalendar().year}-W{dt.isocalendar().week:02d}"


def month_key(dt):
    dt = dt or datetime.utcnow()
    return f"{dt.year}-{dt.month:02d}"


def year_key(dt):
    dt = dt or datetime.utcnow()
    return str(dt.year)


def safe_number(value, default=0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default
