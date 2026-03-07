def validate_quantities(items):
    for i in items:
        if "+" in str(i["quantity"]):
            raise ValueError("Free quantity detected (e.g. 10+2)")

    return True
