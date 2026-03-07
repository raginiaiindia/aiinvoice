import re

GST_REGEX = r"^[0-9A-Z]{15}$"
HSN_REGEX = r"^\d{4}(\d{2})?(\d{2})?$"

def validate_gstin(val):
    return val if val and re.match(GST_REGEX, val) else None

def validate_hsn(val):
    return val if val and re.match(HSN_REGEX, val) else None

def clean_invoice(data):
    data["customer_gstin"] = validate_gstin(
        data.get("customer_gstin")
    )

    for item in data.get("items", []):
        item["hsn_sac"] = validate_hsn(item.get("hsn_sac"))

    return data
