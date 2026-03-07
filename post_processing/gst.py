from decimal import Decimal

def split_gst(items, total_cgst, total_sgst):
    total_value = sum(
        Decimal(i["quantity"]) * Decimal(i["unit_price"])
        for i in items
    )

    for i in items:
        item_value = Decimal(i["quantity"]) * Decimal(i["unit_price"])

        i["cgst_amount"] = (
            item_value / total_value * Decimal(total_cgst)
        ).quantize(Decimal("0.01"))

        i["sgst_amount"] = (
            item_value / total_value * Decimal(total_sgst)
        ).quantize(Decimal("0.01"))

    return items
