from dotenv import load_dotenv

load_dotenv()
import io
import json
import os
from datetime import datetime, timedelta
import secrets
import time
import bcrypt
import fitz
from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    jsonify,
    send_file,
    session,
    url_for,
    send_from_directory,
)
import pandas as pd
from werkzeug.utils import secure_filename
from fastapi.responses import Response
import json
from PIL import Image
import google.generativeai as genai
import logging
from functools import wraps
from flask_cors import CORS
from werkzeug.security import check_password_hash, generate_password_hash
import ssl
import mysql.connector
from mysql.connector import pooling
from datetime import timedelta


utc_now = datetime.utcnow()
import vertexai
from vertexai.preview.generative_models import GenerativeModel
from pdf2image import convert_from_path
from vertexai.preview.generative_models import Part

# to add in app.py
from zoneinfo import ZoneInfo

app = Flask(__name__)
from zoneinfo import ZoneInfo


# Configure the Google Gemini API
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

# Initialize the Gemini model
model = genai.GenerativeModel("gemini-3-pro-preview")

# Allowed file extensions
ALLOWED_EXTENSIONS = {"pdf", "jpeg", "jpg", "png"}

# API Keys loaded from environment variables
API_KEYS = [os.getenv("API_KEY_1"), os.getenv("API_KEY_2")]

# Usage limit per API key per day
USAGE_LIMIT = 10

# MySQL Configuration
MYSQL_CONFIG = {
    "host": os.getenv("MYSQL_HOST"),
    "user": os.getenv("MYSQL_USER"),
    "password": os.getenv("MYSQL_PASSWORD"),
    "database": os.getenv("MYSQL_DB"),
    "auth_plugin": "mysql_native_password",
    "pool_name": "my_pool",
    "pool_size": 5,
    "autocommit": True,
    "buffered": True,
}

# Connection Pool
cnxpool = mysql.connector.pooling.MySQLConnectionPool(**MYSQL_CONFIG)

print("Sender:", os.getenv("EMAIL_ADDRESS"))
print("Password:", os.getenv("EMAIL_PASSWORD"))
def format_currency(value, symbol="₹"):
    if value is None:
        return None
    try:
        return f"{symbol} {float(value):.2f}"
    except:
        return value

def get_db_connection():
    """Returns a new MySQL connection from the pool."""
    cnx = cnxpool.get_connection()
    return cnx


def fix_existing_limits():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET account_limit = 50 WHERE account_limit IS NULL OR account_limit < 50"
    )
    conn.commit()
    cursor.close()
    conn.close()
    print("User limits updated to 50")


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS contact_queries (
        id INT AUTO_INCREMENT PRIMARY KEY,
        email VARCHAR(255) NOT NULL,
        contact VARCHAR(50),
        message TEXT NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """
    )

    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS users (
        id INT AUTO_INCREMENT PRIMARY KEY,
        username VARCHAR(255) UNIQUE,
        email VARCHAR(255) UNIQUE,
        password VARCHAR(255),
        phone VARCHAR(20),                     -- new phone column
        invoices_extracted INT DEFAULT 10,
        passports_extracted INT DEFAULT 10,
        account_limit INT DEFAULT 50,
        manual_limit INT DEFAULT 50,
        api_limit INT DEFAULT 50,
        role VARCHAR(50) DEFAULT 'user'
    )
    """
    )

    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS extraction_history (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT,
        timestamp DATETIME,
        image_name VARCHAR(255),
        pages_extracted INT,
        extraction_type VARCHAR(50),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """
    )

    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS api_keys (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT,
        api_key VARCHAR(255) UNIQUE,
        created_at DATETIME,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """
    )

    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS api_usage (
        id INT AUTO_INCREMENT PRIMARY KEY,
        api_key VARCHAR(255) UNIQUE,
        count INT DEFAULT 0,
        last_used DATE,
        usage_limit INT,
        FOREIGN KEY (api_key) REFERENCES api_keys(api_key) ON DELETE CASCADE
    )
    """
    )

    # ensure admin user exists
    cursor.execute(
        "SELECT * FROM users WHERE username = 'Niraj' AND email = 'connect.aiindia@gmail.com'"
    )
    admin_user = cursor.fetchone()
    if not admin_user:
        cursor.execute(
            """
            INSERT INTO users (username, email, password, role)
            VALUES (
                'Niraj',
                'connect.aiindia@gmail.com',
                '$2b$12$W9ObhLPinBHdnkX1XK6.U.Ub5mgx33abZtEY7xOVfHz5CMnM5tdWm',
                'admin'
            )
        """
        )
        conn.commit()

    cursor.close()
    conn.close()


# Re-initialize the database
init_db()

# Initialize the Flask app
app = Flask(__name__)
CORS(app)
app.secret_key = os.getenv("FLASK_SECRET_KEY", default="fallback-secret-key")

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def check_usage(api_key):
    current_date = datetime.now().date()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    sql = "SELECT * FROM api_usage WHERE api_key = %s"
    cursor.execute(sql, (api_key,))
    usage_entry = cursor.fetchone()
    if not usage_entry:
        sql_insert = (
            "INSERT INTO api_usage (api_key, count, last_used) VALUES (%s, %s, %s)"
        )
        cursor.execute(sql_insert, (api_key, 0, current_date))
        conn.commit()
        usage_entry = {"count": 0, "last_used": current_date, "usage_limit": None}
    else:
        if usage_entry["last_used"] < current_date:
            sql_update = (
                "UPDATE api_usage SET count = 0, last_used = %s WHERE api_key = %s"
            )
            cursor.execute(sql_update, (current_date, api_key))
            conn.commit()
            usage_entry["count"] = 0
            usage_entry["last_used"] = current_date
    usage_limit = (
        usage_entry["usage_limit"]
        if usage_entry["usage_limit"] is not None
        else USAGE_LIMIT
    )
    result = usage_entry["count"] < usage_limit
    cursor.close()
    conn.close()
    return result


# def api_key_required(f):
#     @wraps(f)
#     def decorated_function(*args, **kwargs):
#         api_key = request.headers.get("X-API-Key")
#         if not api_key:
#             return jsonify({"error": "Unauthorized: API Key is required"}), 401
#         conn = get_db_connection()
#         cursor = conn.cursor(dictionary=True)
#         sql = "SELECT * FROM api_usage WHERE api_key = %s"
#         cursor.execute(sql, (api_key,))
#         key_record = cursor.fetchone()
#         if not key_record:
#             cursor.close()
#             conn.close()
#             return jsonify({"error": "Unauthorized: Invalid API Key"}), 401
#         if key_record["count"] >= (
#             key_record["usage_limit"]
#             if key_record["usage_limit"] is not None
#             else USAGE_LIMIT
#         ):
#             cursor.close()
#             conn.close()
#             return jsonify({"error": "Unauthorized: API Key usage limit exceeded"}), 403
#         sql_update = "UPDATE api_usage SET count = count + 1 WHERE api_key = %s"
#         cursor.execute(sql_update, (api_key,))
#         conn.commit()
#         cursor.close()
#         conn.close()
#         return f(*args, **kwargs)

#     return decorated_function

from functools import wraps
from flask import request, jsonify
from datetime import datetime


def api_key_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get("X-API-Key")

        if not api_key:
            return jsonify({"error": "Unauthorized: API Key is required"}), 401

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT au.*
            FROM api_usage au
            JOIN api_keys ak ON au.api_key = ak.api_key
            WHERE au.api_key = %s
            """,
            (api_key,),
        )
        key_record = cursor.fetchone()

        if not key_record:
            cursor.close()
            conn.close()
            return jsonify({"error": "Unauthorized: Invalid API Key"}), 401

        if (
            key_record["usage_limit"] is not None
            and key_record["count"] >= key_record["usage_limit"]
        ):
            cursor.close()
            conn.close()
            return jsonify({"error": "API Key usage limit exceeded"}), 403

        cursor.execute(
            """
            UPDATE api_usage
            SET count = count + 1, last_used = %s
            WHERE api_key = %s
            """,
            (datetime.now().date(), api_key),
        )

        conn.commit()
        cursor.close()
        conn.close()

        return f(*args, **kwargs)

    return decorated_function


def pdf_to_images_pymupdf(file_path):
    doc = fitz.open(file_path)
    images = []
    for page_number in range(len(doc)):
        page = doc.load_page(page_number)
        pix = page.get_pixmap()
        mode = "RGB" if pix.alpha == 0 else "RGBA"
        image = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
        images.append(image)
    return images
HEADER_FIELDS = [
    "invoice_id",
    "invoice_number",
    "invoice_date",
    "due_date",
    "customer_name",
    "customer_gstin",
    "seller_name",
    "seller_gstin",
     "PO_number",
    "DC_date",
    "DC_number",
    "invoice_amount",
    "round_off",
    "total_gst_rate",
    "total_quantity",
    "total_cgst_rate",
    "total_cgst_amount",
    "total_sgst_rate",
    "total_sgst_amount",
    "total_igst_rate",
    "total_igst_amount",
    "total_gst_amount"
]
from datetime import datetime


def generate_invoice_id(conn, invoice_source):
    """
    Generates invoice ID like:
    M20260106001
    E20260106002
    M20260106003
    """

    prefix = "M" if invoice_source == "manual" else "E"
    today = datetime.now().strftime("%Y%m%d")

    cursor = conn.cursor()

    # 🔥 IMPORTANT: DO NOT FILTER BY SOURCE
    cursor.execute(
        """
        SELECT invoice_id
        FROM extraction_history
        WHERE invoice_id IS NOT NULL
        ORDER BY id DESC
        LIMIT 1
    """
    )

    row = cursor.fetchone()

    if row and row[0]:
        last_invoice_id = row[0]
        last_seq = int(last_invoice_id[-3:])
        new_seq = last_seq + 1
    else:
        new_seq = 1

    cursor.close()

    return f"{prefix}{today}{str(new_seq).zfill(3)}"


def extract_invoice_fields(file_path):
    file_ext = os.path.splitext(file_path)[1].lower()
    try:
        if file_ext == ".pdf":
            images = pdf_to_images_pymupdf(file_path)
        else:
            images = [Image.open(file_path)]
        input_prompt = """
    
You are an OCR-based invoice extraction engine with LIMITED,
EXPLICITLY ALLOWED NORMALIZATION for expiry date ONLY.

Character-level copying is mandatory for ALL fields
EXCEPT expiry_date where special rules apply.

=====================
CORE EXTRACTION RULES
=====================
1. Do NOT guess or infer values EXCEPT where explicitly allowed.
2. Preserve original casing, spacing, and punctuation.
3. Never calculate prices, totals, taxes, or quantities
   EXCEPT total_quantity which is explicitly allowed.
4. Never merge multiple item rows into one.
5. Invoice grand total must be extracted exactly as shown
   and labeled as "invoice_amount".
6. Round Off value must be extracted exactly as shown
   and labeled as "round_off".
7. Output ONLY valid JSON (no markdown, no explanation).

=====================
FIELD ISOLATION RULES
=====================
Customer GSTIN ≠ Seller GSTIN
Item Code ≠ HSN ≠ SKU ≠ Product Code ≠ Batch Number
Batch Number must NEVER be merged or reused.

=====================
CGST SGST IGST
=====================
Extract CGST, SGST and IGST at batch level.

Each batch number must be treated as a separate item.

If CGST / SGST / IGST rate and total amount
are given only once at the bottom of the invoice
(for example: “Output CGST @ 2.5% = 1983”):

• Apply the SAME tax rate to all batches of that product.
• Split the given tax amount across batches
  in proportion to each batch’s quantity.
• Assign the calculated tax amount separately
  to each batch item.

Do not combine batches.
Do not create invoice-level tax totals.
Each batch must have its own CGST/SGST/IGST amount.

Do not change quantities or prices.
Only distribute the shown tax amount across batches.


=====================
BATCH-LEVEL ITEM RULES (CRITICAL FINAL)
=====================
1. Each DISTINCT batch number MUST be extracted
   as a SEPARATE item object.

2. If the same product appears with multiple batches:
   - Create ONE item entry PER batch.0
   - Quantity must belong ONLY to that batch.

3. SINGLE-BATCH ITEM RULE:
   If an item row contains:
   - ONLY ONE batch number
   - AND quantity, unit_price (rate), AND total_price
     are ALL explicitly present in the invoice,
   THEN:
   - Extract total_price EXACTLY as shown.
   - Do NOT calculate or modify total_price.

4. MULTI-BATCH ITEM RULE:
   If a product appears with MULTIPLE batch numbers:
   - Create ONE item object PER batch.
   - If total_price is NOT explicitly shown per batch:
       → total_price MUST be calculated as:
         quantity × unit_price
   - This calculation is ALLOWED ONLY at item level.

5. DO NOT calculate, infer, or mention:
   - Any combined total across items
   - Any invoice-level or product-level total
   - Any summed batch total

6. Each item object MUST contain ONLY its own
   batch-level total_price.

7. Batch number MUST be extracted ONLY from item rows.


Accepted batch labels:
  "Batch", "Batch No", "Batch No.", "B.No", "Lot", "Lot No"

=====================
QUANTITY RULES
=====================

1. Extract quantity EXACTLY as shown per batch row.

2. If quantity is written in a combined format such as:
   "20+2", "10 + 1", "5+5"
   → Extract the quantity EXACTLY as written (e.g., "20+2").
   → Do NOT add or calculate the total quantity.
   → Treat the additional quantity as FREE quantity.
   → Set free_item_yn = "1" for that item.

3. If quantity is a single numeric value
   (for example: "10", "5", "2.5"):
   → Set free_item_yn = "0".

4. Do NOT normalize, round, infer, or calculate quantities.

5. If quantity is unclear or unreadable → return null
   AND set free_item_yn = null.

6. total_quantity is the SUM of all item quantities
   ONLY if:
   - quantities are numeric
   - AND quantities do NOT contain free quantity formats like "20+2".

7. If ANY quantity contains a free quantity format
   OR any quantity is unclear
   → total_quantity MUST be null.

=====================
BATCH NUMBER NORMALIZATION RULES (NEW)
=====================
1. If batch_number contains any special character
   (anything other than A–Z, a–z, 0–9):
   - Replace EACH special character with "-" (hyphen).
2. Do NOT remove letters or digits.
3. Do NOT collapse multiple hyphens into one.
4. Do NOT modify casing.

=====================
REFERENCE NUMBER RULES (NEW)
=====================
1. Extract Part Number / Part No / P.No ONLY as "reference_number".
2. Do NOT extract Part Number as item_code.
3. Reference Number must be taken ONLY from labels such as:
   "Part No", "Part Number", "P.No", "Ref No", "Reference No"
4. Reference Number must NOT be reused for any other field.

=====================
ITEM-LEVEL EXPIRY RULES (EXPLICIT INFERENCE ALLOWED)
=====================
Extract expiry ONLY from ITEM ROWS.
Expiry must be on the SAME ROW as:
  item description OR item code OR batch number.

Accepted expiry labels:
  "EXP", "Exp", "Expiry", "Expiry Date",
  "BB", "Best Before", "Use Before"
  =====================
INVOICE & DUE DATE NORMALIZATION RULES (MANDATORY)
=====================
invoice_date and due_date MUST be normalized to:

DD/MM/YYYY

Accepted input formats include:
DD-MM-YYYY
DD/MM/YYYY
YYYY-MM-DD
DD Mon YYYY
Mon DD, YYYY

Rules:
1. Extract the date EXACTLY from its labeled field.
2. Normalize ONLY the format, not the value.
3. If day, month, or year is missing or unclear → return null.
4. If normalization fails → add field name to uncertain_fields.

=====================
EXPIRY DATE NORMALIZATION RULES (MANDATORY)
=====================
Expiry may appear as:
MM/YY   (06/28)
MM/YYYY (06/2028)
YYYY    (2028)

When expiry is in MM/YY format:
1. Take MONTH from expiry (MM).
2. Take YEAR CENTURY from invoice_date or due_date.
3. Combine century + YY to form YYYY.
4. Set DAY to LAST CALENDAR DAY of that month
   (February → 28 or 29 as applicable).

When expiry is in MM/YYYY:
Set DAY to LAST CALENDAR DAY of that month.

When expiry is YEAR only:
Set expiry date to 31/12/YYYY.

FINAL expiry_date format:
DD/MM/YYYY

Do NOT output raw expiry text.
Do NOT ask for clarification.
=====================
ITEM CODE EXTRACTION FROM DESCRIPTION (MANDATORY WITH EXAMPLE)
=====================
1. If the item description STARTS WITH or CONTAINS
   an alphanumeric code separated by hyphens or slashes,
   and the code is followed by brackets, parentheses,
   or descriptive text, that code MUST be extracted
   as "item_code".

2. This applies EVEN IF there is NO explicit
   "Item Code" / "PCode" / "Product Code" label.

3. The extracted code MUST be copied EXACTLY
   as it appears (character-level).

4. Do NOT treat such codes as reference_number.

5. Do NOT infer or generate item_code if no clear
   standalone code is present.

---------------------
EXPLICIT POSITIVE EXAMPLE
---------------------

If item description is:
"SR-02-0497 (Vygon P M Line 200 cm)"

Then output MUST be:
"item_code": "SR-02-0497"

And description MUST remain:
"SR-02-0497 (Vygon P M Line 200 cm)"

---------------------
NEGATIVE EXAMPLES
---------------------
1. "Vygon P M Line 200 cm" → item_code = null
2. "Size SR 02 0497 Tube" → item_code = null (not clearly isolated)
3. "Batch SR-02-0497" → NOT item_code (batch context)

=====================
DATE SOURCE PRIORITY
=====================
Use invoice_date first.
If missing, use due_date.
If both are missing → expiry_date must be null
and added to uncertain_fields.

=====================
VALIDATION RULES
=====================
Year MUST be ≥ invoice year.
If expiry < invoice_date → INVALID.

=====================
NUMBER RULES
=====================
Do NOT correct OCR mistakes.
If digits are unclear → return null.

=====================
ROUND OFF RULES
=====================
1. Extract Round Off ONLY if explicitly present.
2. Accepted labels:
   "Round Off", "RoundOff", "R/O", "R.Off"
3. Do NOT calculate or infer Round Off.
4. If label exists but value is unclear → return null
   and add "round_off" to uncertain_fields.

=====================
OUTPUT RULES
=====================
1. Always include uncertain_fields.
2. If expiry label exists but cannot be resolved →
   add "items[i].expiry_date" to uncertain_fields.
3. Do NOT include empty objects or arrays.
=====================
INVOICE AMOUNT RULES
====================
1. Extract invoice_amount EXACTLY as shown.
2. If a currency symbol or code appears (₹, INR, Rs., $, USD),
   include it BEFORE the amount with a single space.
3. Example: "₹ 12540", "$ 250.00", "INR 8450"
4. Do NOT remove currency.
5. Do NOT normalize or calculate.

=====================
MULTI-PAGE HEADER DEDUPLICATION RULES (MANDATORY)
=====================

1. If the document contains multiple pages:

2. The following HEADER-LEVEL fields MUST be extracted
   ONLY ONCE from the FIRST PAGE where they appear:

   - invoice_number
   - invoice_date
   - due_date
   - customer_name
   - customer_gstin
   - seller_name
   - seller_gstin
   - DC_date
   - DC_number

3. If these header fields appear again on subsequent pages
   with the SAME value:
   → Do NOT repeat, duplicate, or overwrite them.
   → Keep the value extracted from the FIRST page only.

4. Header fields MUST NOT be output multiple times
   based on page count.

5. Only ITEM-LEVEL fields (items array) may be accumulated
   across multiple pages.

6. If a header field is missing on the first page
   but appears on a later page:
   → Extract it ONCE from the earliest page where it appears.

7. Do NOT create page-wise objects.
   Do NOT include page numbers.
   Output must represent a SINGLE invoice.

=====================
OUTPUT JSON STRUCTURE
=====================

{
"invoice_number": "<Invoice Number>",
  "invoice_date": "<Invoice Date>",
  "due_date": "<Due Date>",

  "customer_name": "<Customer Name>",
  "customer_gstin": "<Customer GSTIN>",

  "seller_name": "<Seller Name>",
  "seller_gstin": "<Seller GSTIN>",
  "DC_date":"<DC Date>",
  "DC_number":<DC Number>,
  "PO_number":<PO Number>,
  "total_quantity": <Sum of all item quantities>,
   "total_gst_rate":<gst rate>
  "total_cgst_rate": <total CGST Rate>,
  "total_cgst_amount": <total CGST Amount>,
  "total_sgst_rate": <total SGST Rate>,
  "total_sgst_amount": <total SGST Amount>,
  "total_igst_rate": <total IGST Rate>,
  "total_igst_amount": <total IGST Amount>,    
  "total_gst_amount":<gst amt> 
  "round_off": <Round Off value>,
  "invoice_amount": <Inv amount>,
   
  "items": [
    {
      "description": "<Item Description>",
      "Pack":"<Pack>"
      "Batch":"<BatchNo>",
      "quantity": <Quantity>,
      "free_item_yn":<free_item_yn>",
      "unit_price": <Unit Price>,
      "total_price": <Total Price>,
      "reference_number": "<Reference Number>",
      "hsn_sac": "<HSN/SAC>",
      "item_code": "<Item Code>",
      "expiry_date": "<DD/MM/YYYY>",
      "Discount": "<Disc%>",
      "Value":"<Value>",   
      "Gst":"<Gst>",
       "MRP":"<MRP>",
      "cgst_rate": <CGST Rate>,
      "cgst_amount": <CGST Amount>,
      "sgst_rate": <SGST Rate>,
      "sgst_amount": <SGST Amount>,
      "igst_rate": <IGST Rate>,
      "igst_amount": <IGST Amount>,     
       "GST_AMT":"<GST AMT>", 
    }
  ],

  "uncertain_fields": []

}
#  """
   
       

        all_pages_data = []

        for img in images:
            response = model.generate_content([input_prompt, img])
            response_text = response.text.strip("```").strip()

            if response_text.lower().startswith("json"):
                response_text = response_text[4:].strip()

            if "}" in response_text:
                response_text = response_text[: response_text.rfind("}") + 1]

            try:
                page_data = json.loads(response_text)

                # 🔴 CHANGE 2: remove page_x
                all_pages_data.append(page_data)

            except json.JSONDecodeError as e:
                print(f"JSON parsing error: {e}")
                all_pages_data.append({
                    "error": "Invalid JSON returned from Gemini",
                    "details": response_text,
                })
 
        
        cgst_rates, sgst_rates, igst_rates = set(), set(), set()

        # ===============================
# 🔹 FIX ITEM GST (RATE + AMOUNT)
# ===============================
        for page in all_pages_data:
         for item in page.get("items", []):

            taxable = item.get("total_price") or 0

            # 🔹 1. Derive GST rates from "Gst" field if missing
            gst_text = item.get("Gst")

            if gst_text and not item.get("cgst_rate") and not item.get("igst_rate"):
              try:
                gst_percent = float(gst_text.replace("%", "").strip())
                item["cgst_rate"] = gst_percent / 2
                item["sgst_rate"] = gst_percent / 2
                item["igst_rate"] = 0
              except:
                item["cgst_rate"] = 0
                item["sgst_rate"] = 0
                item["igst_rate"] = 0

        # 🔹 2. Calculate GST amounts
            if item.get("cgst_rate"):
              item["cgst_amount"] = round(taxable * item["cgst_rate"] / 100, 2)

            if item.get("sgst_rate"):
              item["sgst_amount"] = round(taxable * item["sgst_rate"] / 100, 2)

            if item.get("igst_rate"):
               item["igst_amount"] = round(taxable * item["igst_rate"] / 100, 2)

        # 🔹 3. Total GST per item
            item["GST_AMT"] = round(
            (item.get("cgst_amount") or 0)
            + (item.get("sgst_amount") or 0)
            + (item.get("igst_amount") or 0),
            2,
        )
            # ===============================
# 🔹 COLLECT GST RATES + TOTALS
# ===============================
        cgst_rates, sgst_rates, igst_rates = set(), set(), set()
        total_cgst_amount = 0
        total_sgst_amount = 0
        total_igst_amount = 0

        for page in all_pages_data:
         for item in page.get("items", []):
            if item.get("cgst_rate"):
              cgst_rates.add(item["cgst_rate"])
            if item.get("sgst_rate"):
              sgst_rates.add(item["sgst_rate"])
            if item.get("igst_rate"):
              igst_rates.add(item["igst_rate"])

            total_cgst_amount += float(item.get("cgst_amount") or 0)
            total_sgst_amount += float(item.get("sgst_amount") or 0)
            total_igst_amount += float(item.get("igst_amount") or 0)
            
                
                # ===============================
        # 🔹 BUILD FINAL HEADER
        # ===============================
        final_header = {field: None for field in HEADER_FIELDS}

        for page in all_pages_data:
            for field in HEADER_FIELDS:
                value = page.get(field)

                if isinstance(value, dict):
                    value = value.get("value")

                if final_header[field] in (None, "", 0) and value not in (None, "", 0):
                    final_header[field] = value
                    final_header["total_cgst_amount"] = round(total_cgst_amount, 2)
        final_header["total_sgst_amount"] = round(total_sgst_amount, 2)
        final_header["total_igst_amount"] = round(total_igst_amount, 2)

        final_header["total_gst_amount"] = round(
    total_cgst_amount + total_sgst_amount + total_igst_amount,
    2,
)

        # ===============================
        # 🔹 OVERRIDE HEADER GST RATES
        # ===============================
        if len(cgst_rates) == 1:
            final_header["total_cgst_rate"] = list(cgst_rates)[0]

        if len(sgst_rates) == 1:
            final_header["total_sgst_rate"] = list(sgst_rates)[0]

        if len(igst_rates) == 1:
            final_header["total_igst_rate"] = list(igst_rates)[0]

        # ===============================
        # 🔹 TOTAL GST RATE (ADD HERE)
        # ===============================
        total_gst_rate = None

        cgst = final_header.get("total_cgst_rate")
        sgst = final_header.get("total_sgst_rate")
        igst = final_header.get("total_igst_rate")

        if igst and igst > 0:
           total_gst_rate = igst
        elif cgst and sgst:
            total_gst_rate = round(cgst + sgst, 2)

        final_header["total_gst_rate"] = total_gst_rate
        

        # ===============================
        # 🔹 TOTAL GST AMOUNT
        # ===============================
        final_header["total_gst_amount"] = round(
            (final_header.get("total_cgst_amount") or 0)
            + (final_header.get("total_sgst_amount") or 0)
            + (final_header.get("total_igst_amount") or 0),
            2,
        )
       
        # # ===============================
        # # ✅ FINAL OUTPUT
        # # ===============================
        # return {
        #     **final_header,
        #     "items": [
        #         item
        #         for page in all_pages_data
        #         for item in page.get("items", [])
        #     ],
# ===============================
# 🔹 BUILD FINAL OUTPUT
# ===============================
        extracted_data = {
           **final_header,
           "items": [
              item
        for page in all_pages_data
        for item in page.get("items", [])
    ],
}
# ===============================
# 🔹 ENSURE CURRENCY CODE
# ===============================
        if not extracted_data.get("currency_code"):
           extracted_data["currency_code"] = "INR"

        currency_code = extracted_data["currency_code"].upper()
        currency_symbol = "$" if currency_code == "USD" else "₹"

# ===============================
# 🔹 FORMAT CURRENCY FIELDS
# ===============================
        CURRENCY_FIELDS = [
    "invoice_amount",
    "total_gst_amount",
    "total_cgst_amount",
    "total_sgst_amount",
    "total_igst_amount",
    "unit_price",
    "Gst",
    "cgst_amount",
    "sgst_amount",
    "igst_amount",
    "MRP"
]

        def format_currency(value, symbol):
            try:
               if isinstance(value, str):
                  value = value.replace(",", "").strip() 
               return f"{symbol} {float(value):.2f}"
            except:
               return value

        for field in CURRENCY_FIELDS:
          if extracted_data.get(field) is not None:
                 extracted_data[field] = format_currency(
                   extracted_data[field],
                   currency_symbol
        )

# ===============================
# ✅ FINAL RETURN (ONLY ONE)
# ===============================

        return extracted_data
   
    
   
    except Exception as e:
        print("Extraction error:", e)
        return {"error": str(e)}


       


@app.route("/process-invoice", methods=["POST"])
@api_key_required
def process_invoice():
    try:
        if "file" not in request.files:
            return jsonify({"error": "No file part"}), 400
        file = request.files["file"]
        if file.filename == "":
            return jsonify({"error": "No selected file"}), 400
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(filepath)
            upload_message = {"message": f"File uploaded successfully: {filename}"}
            extracted_data = extract_invoice_fields(filepath)
            # 🔹 Attach DB-generated invoice_id to JSON header
            extracted_data["invoice_id"] = invoice_id

            if extracted_data:
                return jsonify(extracted_data), 200
            else:
                logging.error(f"Failed to extract invoice data from {filename}")
                return jsonify({"error": "Failed to extract invoice data"}), 500
        else:
            return jsonify({"error": "Invalid file type"}), 400
    except Exception as e:
        logging.error(f"Error during upload or extraction: {e}")
        return jsonify({"error": "Internal Server Error"}), 500


@app.route("/usage-count", methods=["GET"])
@api_key_required
def get_usage_count():
    api_key = request.headers.get("X-API-Key")
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    sql = "SELECT * FROM api_usage WHERE api_key = %s"
    cursor.execute(sql, (api_key,))
    usage_entry = cursor.fetchone()
    cursor.close()
    conn.close()
    if usage_entry:
        return jsonify(
            {
                "api_key": api_key,
                "usage_count": usage_entry["count"],
                "last_used": usage_entry["last_used"].strftime("%Y-%m-%d"),
            }
        )
    else:
        return jsonify({"error": "API key not found"}), 404


@app.route("/all-usage-counts", methods=["GET"])
@api_key_required
def get_all_usage_counts():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        sql = "SELECT * FROM api_usage"
        cursor.execute(sql)
        usage_entries = cursor.fetchall()
        usage_data = []
        for entry in usage_entries:
            usage_data.append(
                {
                    "api_key": entry["api_key"],
                    "usage_count": entry["count"],
                    "last_used": entry["last_used"].strftime("%Y-%m-%d"),
                }
            )
        cursor.close()
        conn.close()
        return jsonify(usage_data), 200
    except Exception as e:
        return jsonify({"error": f"Internal Server Error: {str(e)}"}), 500


ADMIN_API_KEY = os.getenv("ADMIN_API_KEY")


@app.route("/admin/dashboard")
def admin_dashboard():
    if "user" not in session or session.get("role") != "admin":
        flash("Unauthorized access.")
        return redirect(url_for("login"))
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # fetch all users
        cursor.execute("SELECT * FROM users")
        users = cursor.fetchall()

        # fetch all api_keys
        cursor.execute("SELECT * FROM api_keys")
        api_keys = cursor.fetchall()

        cursor.close()
        conn.close()

        # group api_keys by user_id
        api_keys_dict = {}
        for key in api_keys:
            uid = key["user_id"]
            api_keys_dict.setdefault(uid, []).append(key)

        # build user_activity list and include phone
        user_activity = []
        for u in users:
            u_id = u["id"]
            user_activity.append(
                {
                    "username": u["username"],
                    "email": u["email"],
                    "phone": u.get("phone", "—"),  # ← new phone field
                    "invoices_extracted": u.get("invoices_extracted", 0),
                    "account_limit": u.get("account_limit", 3),
                    "api_keys": api_keys_dict.get(u_id, []),
                    "api_keys": api_keys_dict.get(u_id, []),
                    "user_id": u_id,
                }
            )

        return render_template("admin_dashboard.html", user_activity=user_activity)

    except Exception as e:
        flash(f"Error loading dashboard: {e}")
        return render_template("admin_dashboard.html", user_activity=[])


@app.route("/admin/update-user-limit", methods=["POST"])
def update_user_limit():
    try:
        data = request.get_json()
        user_id = data.get("user_id")
        new_account_limit = data.get("new_account_limit")
        app.logger.info(f"Request data: {data}")
        app.logger.info(
            f"Received user_id: {user_id}, New account limit: {new_account_limit}"
        )
        if not user_id or new_account_limit is None:
            return jsonify({"error": "Missing required parameters"}), 400
        try:
            user_id = int(user_id)
            new_account_limit = int(new_account_limit)
            if new_account_limit < 0:
                return (
                    jsonify({"error": "Account limit must be a positive integer"}),
                    400,
                )
        except ValueError:
            return jsonify({"error": "Account limit must be a valid integer"}), 400
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        sql = "SELECT * FROM users WHERE id = %s"
        cursor.execute(sql, (user_id,))
        user = cursor.fetchone()
        if not user:
            cursor.close()
            conn.close()
            return jsonify({"error": "User not found"}), 404
        app.logger.info(f"User found: {user}")
        sql_update = "UPDATE users SET account_limit = %s WHERE id = %s"
        cursor.execute(sql_update, (new_account_limit, user_id))
        conn.commit()
        modified_count = cursor.rowcount
        cursor.close()
        conn.close()
        app.logger.info(f"Update result: {modified_count}")
        if modified_count == 0:
            return jsonify({"error": "No changes made"}), 404
        app.logger.info(f"User {user_id}'s account limit updated: {new_account_limit}")
        return (
            jsonify(
                {
                    "message": f"Account limit updated to {new_account_limit} for user {user_id}"
                }
            ),
            200,
        )
    except Exception as e:
        app.logger.error(f"Error updating user limit: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/some-a-endpoint", methods=["GET"])
def some_api_endpoint():
    api_key = request.headers.get("X-API-Key")
    if not api_key:
        return jsonify({"error": "API key is missing"}), 400
    print(f"Received API Key: {api_key}")
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    sql = "SELECT * FROM api_usage WHERE api_key = %s"
    cursor.execute(sql, (api_key,))
    current_data = cursor.fetchone()
    print(f"Current Data: {current_data}")
    if not current_data:
        cursor.close()
        conn.close()
        return jsonify({"error": "API key not found"}), 404
    sql_update = "UPDATE api_usage SET count = count + 1 WHERE api_key = %s"
    cursor.execute(sql_update, (api_key,))
    conn.commit()
    cursor.execute(sql, (api_key,))
    updated_data = cursor.fetchone()
    print(f"Updated Data After Increment: {updated_data}")
    cursor.close()
    conn.close()
    return jsonify(
        {"message": "API key usage incremented successfully", "data": updated_data}
    )


@app.route("/", methods=["GET"])
def index():
    if "user" in session:
        return redirect(
            url_for("home_logged_in")
        )  # Redirect to proper logged-in homepage
    return render_template("home.html", logged_in=False)


# New Invoice Route
@app.route("/invoice")
def invoice():
    return render_template("invoice.html")  # After login, redirect to upload_image


@app.route("/passport")
def passport():
    return render_template("passport.html")


from email_validator import validate_email, EmailNotValidError
import phonenumbers
from phonenumbers import NumberParseException


def validate_user_email(email):
    try:
        v = validate_email(email)
        return v.email, None
    except EmailNotValidError as e:
        return None, str(e)


def validate_phone_number(raw_phone, default_region="IN"):
    try:
        pn = phonenumbers.parse(raw_phone, default_region)
        if not phonenumbers.is_valid_number(pn):
            return None, "Phone number is not valid"
        e164 = phonenumbers.format_number(pn, phonenumbers.PhoneNumberFormat.E164)
        return e164, None
    except NumberParseException as e:
        return None, str(e)


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form["username"].strip()
        email_in = request.form["email"].strip()
        phone_in = request.form.get("phone", "").strip()
        password = request.form["password"]  # plain password

        # 1) Validate email
        email, email_err = validate_user_email(email_in)
        if email_err:
            flash(f"Invalid email address: {email_err}", "error")
            return redirect(url_for("signup"))

        # 2) Validate phone
        phone, phone_err = validate_phone_number(phone_in)
        if phone_err:
            flash(f"Invalid phone number: {phone_err}", "error")
            return redirect(url_for("signup"))

        # 3) Store password PLAIN (no hashing)
        plain_password = password

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            sql = """
                INSERT INTO users (username, email, password, phone)
                VALUES (%s, %s, %s, %s)
            """
            cursor.execute(sql, (username, email, plain_password, phone))
            conn.commit()
            cursor.close()
            conn.close()

            flash("Sign up successful! Please log in.", "success")
            return redirect(url_for("login"))

        except Exception as e:
            flash(f"Unexpected Error: {e}", "error")

    return render_template("appsignup.html")


@app.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form["email"]
        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            sql = "SELECT * FROM users WHERE email = %s"
            cursor.execute(sql, (email,))
            user = cursor.fetchone()
            cursor.close()
            conn.close()
            if user:
                session["reset_email"] = email
                flash("Please enter your new password.")
                return redirect(url_for("reset_password"))
            else:
                flash("No account found with this email.")
        except Exception as e:
            flash(f"Error: {e}")
    return render_template("appforget.html")


from flask import render_template
from zoneinfo import ZoneInfo


def to_ist(utc_time):
    return utc_time.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("Asia/Kolkata"))


UPLOAD_FOLDER = os.path.join(os.getcwd(), "uploads", "invoices")


@app.route("/view-invoice/<int:invoice_id>")
def view_invoice(invoice_id):
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT extracted_data, image_name, timestamp
        FROM extraction_history
        WHERE id = %s AND user_id = %s
        """,
        (invoice_id, user_id),
    )

    invoice = cursor.fetchone()

    cursor.close()
    conn.close()

    if not invoice:
        return "Invoice not found", 404

    if not invoice["extracted_data"]:
        return "JSON extraction not available for this invoice", 404

    extracted_json = json.loads(invoice["extracted_data"])

    return render_template(
        "view_invoice_json.html",
        invoice_json=json.dumps(extracted_json, indent=4),
        image_name=invoice["image_name"],
        timestamp=invoice["timestamp"],
    )


@app.route("/invoice-history")
def invoice_history_page():
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT id, timestamp, image_name
        FROM extraction_history
        WHERE user_id = %s
        AND extracted_data IS NOT NULL
        ORDER BY timestamp DESC
        """,
        (user_id,),
    )

    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    invoice_history = []

    for row in rows:
        invoice_history.append(
            {
                "id": row["id"],
                "timestamp_str": row["timestamp"].strftime("%d-%m-%Y %I:%M:%S %p"),
                "image_name": row["image_name"],
            }
        )

    return render_template("view_history.html", invoice_history=invoice_history)


@app.route("/invoice-json/<int:invoice_id>")
def invoice_json(invoice_id):
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT extracted_data
        FROM extraction_history
        WHERE id = %s AND user_id = %s
        """,
        (invoice_id, user_id),
    )

    row = cursor.fetchone()

    cursor.close()
    conn.close()
    if not row or not row["extracted_data"]:
        return "Extraction not available", 404

    extracted_data = json.loads(row["extracted_data"])

    return render_template("view_invoice_json.html", extracted_data=extracted_data)


@app.route("/reset_password", methods=["GET", "POST"])
def reset_password():
    if "reset_email" not in session:
        flash("Invalid reset attempt.")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        new_password = request.form["password"]  # plain password

        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            sql = "UPDATE users SET password = %s WHERE email = %s"
            cursor.execute(sql, (new_password, session["reset_email"]))

            conn.commit()
            cursor.close()
            conn.close()

            session.pop("reset_email", None)
            flash("Password reset successfully.")
            return redirect(url_for("login"))

        except Exception as e:
            flash(f"Error: {e}")

    return render_template("appreset.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        login_input = request.form.get("username")
        password = request.form.get("password")

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            "SELECT * FROM users WHERE username=%s OR email=%s",
            (login_input, login_input),
        )
        user = cursor.fetchone()

        cursor.close()
        conn.close()

        if user and password == user["password"]:
            session.clear()

            session["user_id"] = user["id"]
            session["user"] = user["username"]  # ✅ THIS FIXES IT
            session["role"] = user.get("role", "user")

            if user["role"] == "dmh":
                return redirect(url_for("dmh_dashboard"))
            else:
                return redirect(url_for("dashboard"))

        flash("Invalid login details", "error")

    return render_template("applogin.html")


@app.route("/upload-invoice", methods=["POST"])
def upload_invoice():
    user_id = session.get("user_id")
    role = session.get("role")

    if not user_id or role != "dmh":
        return redirect(url_for("login"))

    conn = get_db_connection()
    cursor = None

    try:
        # ✅ file name must match HTML
        file = request.files.get("file")  # ✅ FIXED
        if not file or file.filename == "":
            flash("No file uploaded!", "error")
            return redirect(url_for("dashboard"))

        filename = secure_filename(file.filename)
        os.makedirs("uploads", exist_ok=True)
        save_path = os.path.join("uploads", filename)
        file.save(save_path)

        invoice_source = (
            "manual"
            if filename.lower().endswith((".jpg", ".jpeg", ".png"))
            else "email"
        )

        # ✅ generate invoice id USING conn
        invoice_id = generate_invoice_id(conn, invoice_source)

        images = (
            pdf_to_images_pymupdf(save_path)
            if filename.lower().endswith(".pdf")
            else [Image.open(save_path)]
        )

        extracted_data = process_invoice(images) or {}

        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO extraction_history
            (invoice_id, user_id, invoice_source, image_name,
             pages_extracted, extraction_type, extracted_data, timestamp)
            VALUES (%s,%s,%s,%s,%s,%s,%s,NOW())
            """,
            (
                invoice_id,
                user_id,
                invoice_source,
                filename,
                len(images),
                "invoice",
                json.dumps(extracted_data),
            ),
        )

        conn.commit()

        flash(f"Invoice uploaded successfully! ID: {invoice_id}", "success")
        return redirect(url_for("view_history"))

    except Exception as e:
        conn.rollback()
        flash(f"Error uploading invoice: {e}", "error")
        return redirect(url_for("dashboard"))

    finally:
        if cursor:
            cursor.close()
        conn.close()


import fitz  # PyMuPDF
from PIL import Image
import io


def pdf_to_images_pymupdf(pdf_path, dpi=200):
    images = []
    zoom = dpi / 72  # 72 is default PDF DPI
    mat = fitz.Matrix(zoom, zoom)

    doc = fitz.open(pdf_path)
    for page in doc:
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        images.append(img)

    doc.close()
    return images



@app.route("/upload_image", methods=["GET", "POST"])
def upload_image():

    user_id = session.get("user_id")
    role = session.get("role")

    if not user_id or role not in ["user", "dmh"]:
        return redirect(url_for("login"))

    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT * FROM users WHERE username = %s", (session["user"],))
        user = cursor.fetchone()

        if not user:
            flash("User not found.", "error")
            return redirect(url_for("login"))

        total_extracted = user.get("invoices_extracted", 0) + user.get(
            "passports_extracted", 0
        )
        extraction_limit = user.get("account_limit") or 50

        if total_extracted >= extraction_limit:
            flash("You have reached your extraction limit.", "error")
            return redirect(url_for("dashboard"))

        if request.method == "POST":

            if session.get("processing", False):
                flash("Please wait until current extraction completes.", "warning")
                return redirect(url_for("dashboard"))

            doc_type = request.form.get("doc_type")
            if doc_type not in ["invoice", "passport"]:
                flash("Invalid document type.", "error")
                return redirect(url_for("dashboard"))

            file = request.files.get("file")
            if not file or not allowed_file(file.filename):
                flash("Invalid file. Upload PDF or Image.", "error")
                return redirect(url_for("dashboard"))

            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(file_path)

            session["processing"] = True

            # =============================
            # INVOICE FLOW
            # =============================
            if doc_type == "invoice":
                ext = filename.lower()
                invoice_source = (
        "manual" if ext.endswith((".jpg", ".jpeg", ".png")) else "email"
    )

                # 1️⃣ MySQL generates unique invoice_id
                invoice_id = generate_invoice_id(conn, invoice_source)

                # 2️⃣ Extract invoice JSON
                extracted_data = extract_invoice_fields(file_path)

                # 3️⃣ ✅ ADD THIS LINE (THIS IS THE ANSWER)
                extracted_data["invoice_id"] = invoice_id

                update_field = "invoices_extracted"

            # =============================
            # PASSPORT FLOW
            # =============================
            else:
                extracted_data = extract_passport_fields(file_path)
                update_field = "passports_extracted"
                invoice_id = None
                invoice_source = None

            if not extracted_data or "error" in extracted_data:
                flash("Extraction failed.", "error")
                session["processing"] = False
                return redirect(url_for("dashboard"))

            page_count = len(extracted_data)

            cursor.execute(
                f"UPDATE users SET {update_field} = {update_field} + %s WHERE username = %s",
                (page_count, session["user"]),
            )

            cursor.execute(
                """
                INSERT INTO extraction_history
                (
                    invoice_id,
                    invoice_source,
                    user_id,
                    timestamp,
                    image_name,
                    pages_extracted,
                    extraction_type,
                    extracted_data,
                    file_path
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    invoice_id,
                    invoice_source,
                    user["id"],
                    datetime.now(),
                    filename,
                    page_count,
                    doc_type,
                    json.dumps(extracted_data),
                    file_path,
                ),
            )

            conn.commit()
            session["processing"] = False

            return render_template(
                "result.html",
                json_data=json.dumps(extracted_data, indent=4, ensure_ascii=False),
                invoice_id=invoice_id,
            )

        return redirect(url_for("dashboard"))

    except Exception as e:
        logging.error(f"Upload error: {e}", exc_info=True)
        flash(f"Error: {e}", "error")
        return redirect(url_for("dashboard"))

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
        session["processing"] = False




@app.route("/download_file", methods=["POST"])
def download_file():
    invoice_data = request.form.get("json_data")
    file_format = request.form.get("file_format")
    if not invoice_data:
        return "No data available for download", 400
    try:
        parsed_data = json.loads(invoice_data)
    except json.JSONDecodeError:
        return "Invalid JSON data", 400
    if file_format == "json":
        json_str = json.dumps(parsed_data, indent=4)
        buffer = io.BytesIO(json_str.encode("utf-8"))
        buffer.seek(0)
        return send_file(
            buffer,
            as_attachment=True,
            download_name="invoice_data.json",
            mimetype="application/json",
        )
    elif file_format == "excel":
        if isinstance(parsed_data, dict) and all(
            key.startswith("page_") for key in parsed_data.keys()
        ):
            data_list = []
            for key, value in parsed_data.items():
                if isinstance(value, dict):
                    value["page"] = key
                data_list.append(value)
            df = pd.DataFrame(data_list)
        else:
            df = pd.DataFrame([parsed_data])
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
            df.to_excel(writer, index=False)
        buffer.seek(0)
        return send_file(
            buffer,
            as_attachment=True,
            download_name="invoice_data.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    if "user" not in session:
        if request.is_json:
            return jsonify({"error": "Unauthorized access. Please log in."}), 401
        flash("Please login first.", "warning")
        return redirect(url_for("login"))
    if session.get("role") == "dmh":
        return redirect(url_for("dmh_dashboard"))

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        sql = "SELECT * FROM users WHERE username = %s"
        cursor.execute(sql, (session["user"],))
        user = cursor.fetchone()

        if not user:
            flash("User not found.", "error")
            if request.is_json:
                return jsonify({"error": "User not found."}), 404
            return redirect(url_for("login"))

        username = user.get("username", "N/A")
        email = user.get("email", "N/A")
        invoices_count = user.get("invoices_extracted", 0)
        passports_count = user.get("passports_extracted", 0)

        sql_history = "SELECT * FROM extraction_history WHERE user_id = %s ORDER BY timestamp DESC"
        cursor.execute(sql_history, (user["id"],))
        history = cursor.fetchall()

        sql_api_key = "SELECT api_key FROM api_keys WHERE user_id = %s"
        cursor.execute(sql_api_key, (user["id"],))
        user_api_key = cursor.fetchone()
        api_key = user_api_key["api_key"] if user_api_key else None

        formatted_history = [
            {
                "timestamp_str": entry["timestamp"].strftime("%Y-%m-%d %H:%M:%S"),
                "image_name": entry.get("image_name", "Unknown"),
                "pages_extracted": entry.get("pages_extracted", 0),
                "extraction_type": entry.get("extraction_type", "N/A"),
            }
            for entry in history
        ]

        if request.is_json:
            return jsonify(
                {
                    "username": username,
                    "email": email,
                    "invoices_count": invoices_count,
                    "passports_count": passports_count,
                    "history": formatted_history,
                    "api_key": api_key,
                }
            )

        return render_template(
            "dashboard.html",
            username=username,
            email=email,
            invoices_count=invoices_count,
            passports_count=passports_count,
            history=formatted_history,
            api_key=api_key,
        )

    except mysql.connector.Error as db_err:
        logging.error(f"Database error: {db_err}", exc_info=True)
        flash(f"Database error: {db_err}", "error")
        if request.is_json:
            return jsonify({"error": str(db_err)}), 500
        return render_template(
            "dashboard.html",
            username="N/A",
            email="N/A",
            invoices_count=0,
            passports_count=0,
            history=[],
            api_key=None,
        )

    except Exception as e:
        logging.error(f"Unexpected error in dashboard: {e}", exc_info=True)
        flash(f"Error: {e}", "error")
        if request.is_json:
            return jsonify({"error": str(e)}), 500
        return render_template(
            "dashboard.html",
            username="N/A",
            email="N/A",
            invoices_count=0,
            passports_count=0,
            history=[],
            api_key=None,
        )

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.route("/dmh/dashboard")
def dmh_dashboard():
    if session.get("role") != "dmh":
        return redirect(url_for("login"))

    return render_template("dmh_dashboard.html")


@app.route("/view_history")
def view_history():
    # if "user" not in session:
    #     flash("Please login first.")
    #     return redirect(url_for("login"))
    user_id = session.get("user_id")
    role = session.get("role")

    if not user_id or role not in ["user", "dmh"]:
        return redirect(url_for("login"))
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        sql = "SELECT id FROM users WHERE username = %s"
        cursor.execute(sql, (session["user"],))
        user = cursor.fetchone()
        if user:
            sql_history = "SELECT * FROM extraction_history WHERE user_id = %s ORDER BY timestamp DESC"
            cursor.execute(sql_history, (user["id"],))
            invoice_history = cursor.fetchall()
            formatted_history = []
            for entry in invoice_history:
                entry["timestamp_str"] = entry["timestamp"].strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                formatted_history.append(entry)
            cursor.close()
            conn.close()
            return render_template(
                "view_history.html", invoice_history=formatted_history
            )
        else:
            cursor.close()
            conn.close()
            flash("User not found.")
    except Exception as e:
        flash(f"Error: {e}")
    return render_template("view_history.html", invoice_history=[])


@app.route("/api/extract_invoice", methods=["POST"])
def api_extract_invoice():
    if "api_key" not in request.headers:
        return jsonify({"error": "Missing API key"}), 401
    api_key = request.headers["api_key"]
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    sql = "SELECT * FROM api_keys WHERE api_key = %s"
    cursor.execute(sql, (api_key,))
    api_key_record = cursor.fetchone()
    if not api_key_record:
        cursor.close()
        conn.close()
        return jsonify({"error": "Invalid API key"}), 403
    file = request.files.get("file")
    if not file or not allowed_file(file.filename):
        cursor.close()
        conn.close()
        return (
            jsonify(
                {"error": "Invalid file type. Please upload a valid PDF or image."}
            ),
            400,
        )
    filename = secure_filename(file.filename)
    file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(file_path)
    invoice_data = extract_invoice_fields(file_path)
    if invoice_data:
        sql_update = (
            "UPDATE users SET invoices_extracted = invoices_extracted + 1 WHERE id = %s"
        )
        cursor.execute(sql_update, (api_key_record["user_id"],))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"success": True, "invoice_data": invoice_data}), 200
    else:
        cursor.close()
        conn.close()
        return (
            jsonify({"success": False, "error": "Failed to extract invoice data"}),
            500,
        )


@app.route("/generate_api_key", methods=["POST"])
def generate_api_key():
    if "user" not in session:
        return jsonify({"error": "Unauthorized. Please log in first."}), 401
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    sql = "SELECT id FROM users WHERE username = %s"
    cursor.execute(sql, (session["user"],))
    user = cursor.fetchone()
    if not user:
        cursor.close()
        conn.close()
        return jsonify({"error": "User not found."}), 404
    sql_check = "SELECT * FROM api_keys WHERE user_id = %s"
    cursor.execute(sql_check, (user["id"],))
    existing_api_key = cursor.fetchone()
    if existing_api_key:
        cursor.close()
        conn.close()
        return jsonify({"error": "You have already generated an API key."}), 400
    api_key = secrets.token_hex(32)
    sql_insert = (
        "INSERT INTO api_keys (user_id, api_key, created_at) VALUES (%s, %s, %s)"
    )
    cursor.execute(sql_insert, (user["id"], api_key, datetime.utcnow()))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"api_key": api_key, "success": True})


@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("Logged out successfully!")
    return redirect(url_for("index"))


@app.route("/admin/set-account-limit", methods=["POST"])
def set_account_limit():
    try:
        data = request.get_json()
        new_manual_limit = data.get("manual_limit", 50)
        new_api_limit = data.get("api_limit", 50)
        if new_manual_limit < 0 or new_api_limit < 0:
            return jsonify({"error": "Limits must be positive integers"}), 400
        total_account_limit = new_manual_limit + new_api_limit
        conn = get_db_connection()
        cursor = conn.cursor()
        sql = "UPDATE users SET manual_limit = %s, api_limit = %s, account_limit = %s"
        cursor.execute(sql, (new_manual_limit, new_api_limit, total_account_limit))
        conn.commit()
        modified_count = cursor.rowcount
        cursor.close()
        conn.close()
        if modified_count == 0:
            return jsonify({"message": "No users updated"}), 404
        return (
            jsonify(
                {
                    "message": f"Account limits set to {total_account_limit} for all users"
                }
            ),
            200,
        )
    except Exception as e:
        app.logger.error(f"Error setting account limits: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/get_api_key", methods=["GET"])
def get_api_key():
    if "user" not in session:
        return jsonify({"error": "Unauthorized. Please log in first."}), 401
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    sql = "SELECT id FROM users WHERE username = %s"
    cursor.execute(sql, (session["user"],))
    user = cursor.fetchone()
    if not user:
        cursor.close()
        conn.close()
        return jsonify({"error": "User not found."}), 404
    sql_api = "SELECT api_key FROM api_keys WHERE user_id = %s"
    cursor.execute(sql_api, (user["id"],))
    api_key = cursor.fetchone()
    cursor.close()
    conn.close()
    if api_key:
        return jsonify({"api_key": api_key["api_key"], "success": True})
    else:
        return jsonify({"error": "No API key found."}), 404


@app.route("/api/routes", methods=["GET"])
def list_routes():
    routes = []
    for rule in app.url_map.iter_rules():
        routes.append(
            {"endpoint": rule.endpoint, "methods": list(rule.methods), "url": str(rule)}
        )
    return jsonify({"routes": routes})


port = int(os.getenv("PORT", 8080))


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/pricing")
def pricing():
    return render_template("pricing.html")


@app.route("/contact_sales")
def contact_sales():
    return render_template("about.html")


# Add this at the end of your application.py and run once


import os

# from dotenv import load_dotenv
# load_dotenv()
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# Print current working directory to confirm
print("Current working directory:", os.getcwd())

# Load .env file
load_dotenv()  # Looks for .env in the current working directory

# Email config
# Email Configuration
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")  # e.g., 'your_email@gmail.com'
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")  # e.g., Gmail app-specific password
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL")  # e.g., 'recipient@example.com'
SMTP_SERVER = "smtp.gmail.com"  # Adjust for your email provider
SMTP_PORT = 587


def send_email(email, contact, message):
    missing_configs = []
    if not EMAIL_ADDRESS:
        missing_configs.append("EMAIL_ADDRESS")
    if not EMAIL_PASSWORD:
        missing_configs.append("EMAIL_PASSWORD")
    if not RECIPIENT_EMAIL:
        missing_configs.append("RECIPIENT_EMAIL")
    if not SMTP_SERVER:
        missing_configs.append("SMTP_SERVER")
    if not SMTP_PORT:
        missing_configs.append("SMTP_PORT")

    if missing_configs:
        print(
            f"Email configuration missing: {', '.join(missing_configs)}. Check .env file."
        )
        return False

    msg = MIMEMultipart()
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = RECIPIENT_EMAIL
    msg["Subject"] = "New Query Submission from AI Infinite"

    # Format body nicely whether it's contact or demo
    if contact is not None:
        body = f"""
        Hello,

        A new query has been received through the AI Infinite contact form:

        Email: {email}
        Contact Number: {contact or 'Not provided'}
        Message: {message}

        Thank you,
        AI Infinite Team
        """
    else:
        body = message  # If it's demo, just use the already formatted message

    msg.attach(MIMEText(body, "plain"))

    try:
        server = smtplib.SMTP(SMTP_SERVER, int(SMTP_PORT))
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.sendmail(EMAIL_ADDRESS, RECIPIENT_EMAIL, msg.as_string())
        server.quit()
        print("Email sent successfully")
        return True
    except Exception as e:
        print(f"Email error: {e}")
        return False


@app.route("/submit", methods=["POST"])
def submit_query():
    print("Received form submission")
    email = request.form.get("email")
    contact = request.form.get("contact")
    message = request.form.get("message")
    print(f"Form data: email={email}, contact={contact}, message={message}")

    if not email or not message:
        print("Validation failed: Email or message missing")
        return (
            jsonify({"success": False, "message": "Email and message are required"}),
            400,
        )

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO contact_queries (email, contact, message) VALUES (%s, %s, %s)",
            (email, contact, message),
        )
        conn.commit()
        print("Query stored in database")
    except Exception as e:
        print(f"Database error: {e}")
        return jsonify({"success": False, "message": "Error storing query"}), 500
    finally:
        cursor.close()
        conn.close()

    if send_email(email, contact, message):
        print("Email sent successfully")
        return jsonify({"success": True, "message": "Query stored and email sent"})
    else:
        print("Email sending failed")
        return (
            jsonify(
                {"success": False, "message": "Query stored, but failed to send email"}
            ),
            200,
        )


@app.route("/schedule", methods=["POST"])
def schedule_demo():
    print("Received demo submission")
    name = request.form.get("name")
    email = request.form.get("company-email")
    timezone = request.form.get("timezone")

    if not email:
        print("Validation failed: Email missing")
        return jsonify({"success": False, "message": "Email is required"}), 400

    message = (
        "Hello,\n"
        "A new demo request has been issued by\n\n"
        f"Name: {name or 'Not provided'}\n"
        f"Email: {email}\n"
        f"Timezone: {timezone or 'Not specified'}\n\n"
        "Thank you."
    )

    if send_email(email, None, message):
        print("Demo email sent successfully")
        return jsonify(
            {"success": True, "message": "Demo request processed and email sent"}
        )
    else:
        print("Demo email sending failed")
        return (
            jsonify(
                {
                    "success": False,
                    "message": "Demo request processed, but failed to send email",
                }
            ),
            200,
        )


@app.route("/home")
def home_logged_in():
    if "user" not in session:
        print("User not in session. Redirecting to index.")
        return redirect(url_for("index"))
    print(f"User is in session: {session['user']}")
    return render_template("home.html", logged_in=True, username=session["user"])


@app.context_processor
def inject_user():
    return {"logged_in": "user" in session, "username": session.get("user")}



if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)
    app.run(host="0.0.0.0", port=port, debug=True)
