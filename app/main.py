from extractor.gemini_extract import extract_invoice_data
from post_processing.pipeline import process_invoice

def run(pdf_path):
    raw_data = extract_invoice_data(pdf_path)
    final_json = process_invoice(raw_data)
    return final_json
