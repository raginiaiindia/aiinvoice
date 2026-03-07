from datetime import datetime
from .expiry import normalize_expiry
from .gst import split_gst
from .quantity import validate_quantities
from .validation import final_validation

def process_invoice(raw_data):
    invoice_date = datetime.strptime(
        raw_data["invoice_date"], "%d/%m/%Y"
    )

    # Expiry normalization
    for item in raw_data["items"]:
        item["expiry"] = normalize_expiry(
            item.get("expiry"), invoice_date
        )

    # Quantity validation
    validate_quantities(raw_data["items"])

    # GST calculation
    raw_data["items"] = split_gst(
        raw_data["items"],
        raw_data["invoice_level_cgst"],
        raw_data["invoice_level_sgst"]
    )

    # Final validation
    final_validation(raw_data)

    return raw_data
