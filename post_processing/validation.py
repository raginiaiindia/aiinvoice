def final_validation(data):
    required = ["invoice_date", "items"]

    for field in required:
        if field not in data:
            raise ValueError(f"Missing field: {field}")

    if not data["items"]:
        raise ValueError("No invoice items found")

    return True
