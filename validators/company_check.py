import json

with open("master/pharma_master.json") as f:
    MASTER = json.load(f)

def verify_company(data):
    seller = data.get("seller_name")

    if seller in MASTER:
        if data.get("seller_gstin") != MASTER[seller]["gstin"]:
            data["seller_gstin"] = None

    return data
