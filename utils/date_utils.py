from datetime import datetime


def today_ddmmyyyy():
    return datetime.now().strftime("%d.%m.%Y")


def get_export_filename(platform_name="platstat", extension="xlsx", date_obj=None):
    if not date_obj:
        date_obj = datetime.now()
    date_str = date_obj.strftime("%Y-%m-%d")
    platform_clean = (platform_name or "platstat").lower().strip()
    ext_clean = extension.lstrip(".").lower()
    return f"{platform_clean}-{date_str}.{ext_clean}"