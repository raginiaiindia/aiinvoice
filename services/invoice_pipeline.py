from prompts.invoice_prompt import INVOICE_PROMPT
from services.gemini_extractor import extract_page
from services.json_parser import safe_json_parse
from validators.invoice_validator import clean_invoice
from validators.company_check import verify_company

def process_invoice(images):
    final_pages = {}

    for i, img in enumerate(images):
        raw = extract_page(img, INVOICE_PROMPT)
        parsed = safe_json_parse(raw)
        cleaned = clean_invoice(parsed)
        verified = verify_company(cleaned)

        final_pages[f"page_{i+1}"] = verified

    return final_pages
