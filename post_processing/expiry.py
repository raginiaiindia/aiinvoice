import calendar
from datetime import datetime

def normalize_expiry(expiry_raw, invoice_date):
    if not expiry_raw:
        return None

    if len(expiry_raw) == 5:  # MM/YY
        month, yy = expiry_raw.split("/")
        year = int(invoice_date.year / 100) * 100 + int(yy)
        last_day = calendar.monthrange(year, int(month))[1]
        return f"{last_day:02d}/{month}/{year}"

    if len(expiry_raw) == 4:  # YYYY
        return f"31/12/{expiry_raw}"

    return expiry_raw
