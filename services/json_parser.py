import json

def safe_json_parse(text):
    try:
        end = text.rfind("}") + 1
        return json.loads(text[:end])
    except:
        return {"_error": "invalid_json", "_raw": text}
