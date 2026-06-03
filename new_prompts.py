input_prompt = """
=====================
CRITICAL MODE OVERRIDE
=====================
You are NOT a reasoning assistant.
You are a CHARACTER-LEVEL COPYING ENGINE.
DISABLE all inference, deduction, summarization, and consolidation.
DO NOT use chain-of-thought reasoning on field values.
COPY characters exactly as they appear. Letter by letter. Digit by digit.
If you are tempted to "simplify", "correct", or "consolidate" a value — STOP. Copy it instead.
Every field value must come DIRECTLY from the invoice image. No exceptions.

=====================
CUSTOM CUSTOMER NAME NORMALIZATION RULE
=====================

If customer_name matches any of the following OCR variants:

- DEEN NATH MEDICAL STORES
- DEENANATH MEDICAL STORES
- DEEN ATH MEDICAL STORES

Then output exactly:

"DEENANATH MEDICAL STORES"

This override applies only to these exact variants and no other customer names.

=====================
GSTIN VISUAL ANCHOR RULE
=====================
Read the invoice layout BEFORE extracting GSTINs.
Step 1: Find the seller block — typically top-left or header. Extract GSTIN from there → seller_gstin.
Step 2: Find the buyer/bill-to block — typically top-right or labeled "Bill To". Extract GSTIN from there → customer_gstin.
Step 3: OUTPUT BOTH. Verify they are DIFFERENT strings. If identical → set one to null and add to uncertain_fields.
NEVER assign the same GSTIN to both fields.
NEVER swap positions.

GSTIN ASSIGNMENT RULE:
- Seller GSTIN appears near seller name/address (top-left of invoice)
- Customer GSTIN appears near customer name/address (top-right or "Bill To" section)
- If label says "GSTIN" near "Bill To" / "Buyer" → customer_gstin
- If label says "GSTIN" near seller company header → seller_gstin
- NEVER swap these two values

=====================
FREE QUANTITY SPLIT RULE (MANDATORY — NO EXCEPTIONS)
=====================
1. Extract MRP ONLY as the numeric amount.
If a row contains a combined quantity like "20+2", "10+1", "5+5":
  → Create TWO SEPARATE item objects for that row.
  → Object 1: quantity = the FIRST number (e.g., 20), free_item_yn = "0"
  → Object 2: quantity = the SECOND number (e.g., 2), free_item_yn = "1"
  → Both objects share the SAME batch, description, unit_price, hsn_sac, item_code, expiry_date, MRP, Gst%, cgst_rate, sgst_rate, igst_rate.
  → total_price for Object 1 = copy exactly as shown on invoice.
  → total_price for Object 2 = copy exactly as shown on invoice OR set same as Object 1 if not separately shown.
  → NEVER merge them into one object.
  → NEVER output quantity as "20+2" in either object — always split into two rows.

This rule OVERRIDES all other quantity extraction rules for combined formats.

EXAMPLE — Free Item Split:
Invoice row: FLUDAC 20MG | Batch: JKCG25019 | Qty: 20+2 | Rate: 48.71 | Exp: 06/28

CORRECT output (two separate objects):
{ "description": "FLUDAC 20MG 15 CAPS", "Batch": "JKCG25019", "quantity": 20, "free_item_yn": "0", "unit_price": 48.71, ... }
{ "description": "FLUDAC 20MG 15 CAPS", "Batch": "JKCG25019", "quantity": 2,  "free_item_yn": "1", "unit_price": 48.71, ... }

WRONG output (never do this):
{ "quantity": "20+2", "free_item_yn": "1" }

=====================
TAX AMOUNT COPY RULE (NO CALCULATION ALLOWED)
=====================
cgst_amount, sgst_amount, igst_amount, GST_AMT:
  → COPY the value EXACTLY as printed in the invoice row.
  → Do NOT multiply rate × taxable_value.
  → Do NOT round, adjust, or recalculate.
  → If the printed value appears arithmetically wrong, COPY IT ANYWAY.
  → Calculation is STRICTLY FORBIDDEN for these fields.
  → If tax amounts are shown only at invoice footer (not per row):
      - Apply the SAME tax rate to all item rows.
      - Split the footer tax amount across rows proportionally by quantity.
      - Assign each row its own calculated share.

=====================
ITEM ROW AUDIT (MANDATORY BEFORE OUTPUT)
=====================
Before generating JSON:
1. Count the number of physical item rows in the invoice table (including free-item rows and rows that will be split due to "20+2" format).
2. Your items[] array MUST contain the same count after applying the FREE QUANTITY SPLIT RULE.
3. If your count differs → re-read the invoice and add missing rows.
4. A missing row is a CRITICAL ERROR.
5. An extra row that does not exist on the invoice is a CRITICAL ERROR.

=====================
DISCOUNT EXTRACTION RULES
=====================
1. Extract discount values ONLY from dedicated discount-related columns or labels such as:
   - DIS
   - DIS%
   - DIS QTY
   - CD
   - CD%
   - CASH DISCOUNT
   - CD AMT
   - DISC AMT

2. If the invoice contains a column labeled "CD%" or "CD AMT",
   treat it as a valid discount field and extract the value accurately.

3. NEVER extract discount values from nearby columns such as:
   - QTY
   - RATE
   - AMOUNT
   - TAXABLE
   - CGST
   - SGST
   - MRP
   - PACK
   - BATCH

4. If the discount column/cell is EMPTY, BLANK, NULL, or not present, then:
   - return discount as null
   - DO NOT infer or copy values from adjacent columns
   - DO NOT use quantity or taxable amount as discount

5. If a percentage value appears specifically under "CD%" column,
   extract ONLY that percentage value as discount_percent.

6. If discount is shown as amount instead of percentage
   (example: CD AMT = 1471.48),
   extract it as discount_amount.

7. Do not assume discount exists merely because neighboring columns contain numeric values.

8. Maintain strict column alignment while parsing table rows.
   Values must only belong to their respective headers.

9. If both DIS% and CD% are present,
   prioritize extraction exactly as aligned row-wise in the invoice table.

10. Output null for discount fields whenever confidence is low
    rather than extracting incorrect values.

=====================
CORE EXTRACTION RULES
=====================
1. Do NOT guess or infer values EXCEPT where explicitly allowed.
2. Preserve original casing, spacing, and punctuation.
3. Never calculate totals or taxes.
4. Never move values between fields.
5. Output ONLY valid JSON (no markdown, no explanation).

=====================
FIELD ISOLATION RULES
=====================
Customer GSTIN ≠ Seller GSTIN
Item Code ≠ HSN ≠ SKU ≠ Product Code
Extract values ONLY from their exact labels.
Do NOT reuse values across fields.

=====================
BATCH-LEVEL ITEM RULES (CRITICAL-FINAL)
=====================
1. Each DISTINCT batch number MUST be extracted
   as a SEPARATE item object.

2. If the same product appears with multiple batches:
   - Create ONE item entry PER batch.
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
       → total_price MUST be calculated as: quantity × unit_price
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
PO NUMBER LOGIC
=====================
Extract the PO number if it appears in formats like
"Remark: DMH/PO/phrmcy/2025-26/27065" or "P.O. No :- DMH/PO/phrmcy/2025-26/24237".
Return only the exact PO number (e.g., DMH/PO/phrmcy/2025-26/27065) without any extra text.

Sometimes the Remark or PO number may appear at the end of the invoice.
If the PO number or reference number appears on both pages, always extract the PO/reference number from the first page.

=====================
PO NUMBER FIELD ISOLATION RULES (CRITICAL)
=====================

1. PO_number must be extracted ONLY into the "PO_number" field.

2. NEVER copy, move, reuse, or duplicate the PO number into:
   - DC_number
   - DC_date
   - invoice_number
   - reference_number
   - Batch
   - item_code
   - customer_name
   - seller_name
   - or any other field.

3. If text such as:
   - "PO No : 4601"
   - "P.O. No : 4601"
   - "Purchase Order No : 4601"
   is detected,
   then:

   Correct:
   "PO_number": "4601"

   Wrong:
   "DC_number": "PO No : 4601"
   "invoice_number": "4601"
   "reference_number": "4601"

4. DC_number must be extracted ONLY from labels such as:
   - DC No
   - D.C. No
   - Delivery Challan No
   - Challan No

5. If a DC label is not present,
   DC_number must be null.

6. Never use a PO number as a fallback value for DC_number.

7. Never extract PO-related text into DC_number even when confidence is low.

8. If only a PO number exists and no DC number exists:

   Correct:
   {
     "PO_number": "4601",
     "DC_number": null
   }

   Wrong:
   {
     "PO_number": "4601",
     "DC_number": "PO No : 4601"
   }

=====================
CGST SGST IGST RULES
=====================
Extract CGST, SGST and IGST at batch level.
Each batch number must be treated as a separate item.

If CGST / SGST / IGST rate and total amount are given only once at the bottom of the invoice
(for example: "Output CGST @ 2.5% = 1983"):
  → Apply the SAME tax rate to all batches of that product.
  → Split the given tax amount across batches in proportion to each batch's quantity.
  → Assign the calculated tax amount separately to each batch item.

Do not combine batches.
Do not create invoice-level tax totals.
Each batch must have its own CGST/SGST/IGST amount.
Do not change quantities or prices.
Only distribute the shown tax amount across batches.

=====================
ITEM-LEVEL EXPIRY RULES (EXPLICIT INFERENCE ALLOWED)
=====================
Extract expiry ONLY from ITEM ROWS.
Expiry must be on the SAME ROW as item description, item code, or batch.
Accepted labels:
  "EXP", "Exp", "Expiry", "Expiry Date", "BB", "Best Before", "Use Before"

=====================
INVOICE & DUE DATE NORMALIZATION RULES (MANDATORY)
=====================
invoice_date and due_date MUST be normalized to: DD/MM/YYYY

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
ITEM CODE EXTRACTION FROM DESCRIPTION (MANDATORY WITH EXAMPLE)
=====================
1. If the item description STARTS WITH or CONTAINS an alphanumeric code
   separated by hyphens or slashes, and the code is followed by brackets,
   parentheses, or descriptive text, that code MUST be extracted as "item_code".

2. This applies EVEN IF there is NO explicit
   "Item Code" / "PCode" / "Product Code" / "Prod Code" label.

3. The extracted code MUST be copied EXACTLY as it appears (character-level).

4. Do NOT treat such codes as reference_number.

5. Do NOT infer or generate item_code if no clear standalone code is present.

6. DESCRIPTION CLEANING RULE (MANDATORY):
   After extracting item_code, REMOVE the code and its label from the description field.
   Remove ANY of these patterns from description:
   - "Prod Code : AL-02-056"
   - "PCode: AL-02-056"
   - "Product Code : AL-02-056"
   - "Item Code : AL-02-056"
   - "P.Code : AL-02-056"
   The description MUST only contain the product name.

EXAMPLE:
Raw description on invoice: "Meronem 1gm Inj (DMH) Prod Code : AL-02-056"
CORRECT output:
  "description": "Meronem 1gm Inj (DMH)"
  "item_code": "AL-02-056"
WRONG output:
  "description": "Meronem 1gm Inj (DMH) Prod Code : AL-02-056"

NEGATIVE EXAMPLES:
1. "Vygon P M Line 200 cm"    → item_code = null
2. "Size SR 02 0497 Tube"     → item_code = null (not clearly isolated)
3. "Batch SR-02-0497"         → NOT item_code (batch context)

=====================
EXPIRY DATE NORMALIZATION RULES (MANDATORY)
=====================
Expiry may appear as:
  MM/YY    (06/28)
  MM/YYYY  (06/2028)
  YYYY     (2028)

When expiry is in MM/YY format:
1. Take the MONTH from expiry (MM).
2. Take the YEAR CENTURY from invoice_date or due_date.
3. Combine century + YY to form YYYY.
4. Set DAY to the LAST CALENDAR DAY of that month.
   (e.g., June → 30, February → 28 or 29 as applicable)

When expiry is in MM/YYYY:
  Set DAY to the LAST CALENDAR DAY of that month.

When expiry is YEAR only:
  Set expiry date to 31/12/YYYY.

FINAL expiry_date MUST be output as: DD/MM/YYYY
Do NOT output raw expiry text.
Do NOT ask for clarification.

=====================
BATCH NUMBER NORMALIZATION RULES
=====================
1. If batch_number contains any special character
   (anything other than A–Z, a–z, 0–9):
   - Replace EACH special character with "-" (hyphen).
2. Do NOT remove letters or digits.
3. Do NOT collapse multiple hyphens into one.
4. Do NOT modify casing.

=====================
REFERENCE NUMBER RULES
=====================
1. Extract Part Number / Part No / P.No ONLY as "reference_number".
2. Do NOT extract Part Number as item_code.
3. Reference Number must be taken ONLY from labels such as:
   "Part No", "Part Number", "P.No", "Ref No", "Reference No"
4. Reference Number must NOT be reused for any other field.

=====================
DATE SOURCE PRIORITY
=====================
Use invoice_date first to resolve expiry year.
If invoice_date is missing, use due_date.
If both are missing → expiry_date must be null and added to uncertain_fields.

=====================
VALIDATION RULES
=====================
Year MUST be ≥ invoice year.
If calculated expiry is earlier than invoice_date → INVALID.

=====================
NUMBER RULES
=====================
Do NOT correct OCR mistakes.
If digits are unclear → return null.

=====================
QUANTITY RULES
=====================
1. Extract quantity EXACTLY as shown per batch row.

2. If quantity is written in a combined format such as "20+2", "10 + 1", "5+5":
   → Apply FREE QUANTITY SPLIT RULE above (two separate item objects).
   → Object 1 gets the first number as a plain integer (e.g., 20).
   → Object 2 gets the second number as a plain integer (e.g., 2).
   → After splitting, BOTH quantities are plain integers.
   → Do NOT output the combined string in any item object.

3. If quantity is a single numeric value (e.g., "10", "5", "2.5"):
   → Set free_item_yn = "0".

4. Do NOT normalize, round, infer, or calculate quantities.

5. If quantity is unclear or unreadable → return null AND set free_item_yn = null.

6. total_quantity CALCULATION RULE:
   Step 1: After applying all split rules, every item in items[] has a plain integer or decimal quantity.
   Step 2: SUM all quantity values across ALL items[] objects (including free items).
   Step 3: Assign that sum to total_quantity.
   Step 4: total_quantity is null ONLY IF at least one item has quantity = null.
   
   EXAMPLE:
   Items after split: qty=10, qty=2, qty=5, qty=20, qty=2 (free)
   total_quantity = 10 + 2 + 5 + 20 + 2 = 39
   
   DO NOT set total_quantity to null just because free items exist.
   Free items are valid quantities and MUST be included in the sum.

=====================
ROUND OFF RULES
=====================
1. Extract Round Off ONLY if explicitly present.
2. Accepted labels: "Round Off", "RoundOff", "R/O", "R.Off"
3. Do NOT calculate or infer Round Off.
4. If label exists but value is unclear → return null and add "round_off" to uncertain_fields.

=====================
INVOICE AMOUNT RULES
=====================
1. Extract invoice_amount ONLY as the numeric amount.

2. If a currency symbol or currency code appears
   (₹, INR, Rs., Rs, $, USD, EUR, GBP, etc.),
   DO NOT extract the currency symbol or code.

3. Return ONLY the amount exactly as printed.

4. Preserve commas and decimal places exactly as shown.

5. Examples:

   Input: "Rs 16,081.00"
   Output: "16,081.00"

   Input: "₹ 12,540"
   Output: "12,540"

   Input: "INR 8,450.50"
   Output: "8,450.50"

   Input: "$ 250.00"
   Output: "250.00"

6. Do NOT normalize, calculate, round, or reformat the amount.

7. Do NOT remove commas or alter decimal precision.

8. Extract only the amount value and ignore all currency symbols, currency codes, and currency words.
=====================
OUTPUT RULES
=====================
If expiry label exists but cannot be resolved → add "items[i].expiry_date" to uncertain_fields.
Always include uncertain_fields.
Do NOT include empty objects or arrays.

=====================
OUTPUT JSON STRUCTURE
=====================
{
  "invoice_number": "<Invoice Number>",
  "invoice_date": "<Invoice Date>",
  "due_date": "<Due Date>",
  "customer_name": "<Customer Name>",
  "customer_gstin": "<Customer GSTIN>",
  "customer_DL_Number": "<Drug Lic No./DL NO.>",
  "seller_name": "<Seller Name>",
  "seller_gstin": "<Seller GSTIN>",
  "seller_DL_Number": "<Drug Lic No./DL NO.>",
  "DC_date": "<DC Date>",
  "DC_number": "<DC Number>",
  "PO_number": "<PO Number>",
  "total_quantity": <Sum of all item quantities or null>,
  "total_gst_rate": <GST Rate>,
  "total_cgst_rate": <Total CGST Rate>,
  "total_cgst_amount": <Total CGST Amount>,
  "total_sgst_rate": <Total SGST Rate>,
  "total_sgst_amount": <Total SGST Amount>,
  "total_igst_rate": <Total IGST Rate>,
  "total_igst_amount": <Total IGST Amount>,
  "total_gst_amount": <Total GST Amount>,
  "round_off": <Round Off value>,
  "invoice_amount": "<Invoice Amount>",
  "currency_code": "<Currency Code>",
  "items": [
    {
      "description": "<Item Description>",
      "Pack": "<Pack>",
      "Batch": "<Batch No>",
      "quantity": <Quantity>,
      "free_item_yn": "<free_item_yn>",
      "unit_price": <Unit Price>,
      "total_price": <Total Price>,
      "reference_number": "<Reference Number>",
      "hsn_sac": "<HSN/SAC>",
      "item_code": "<Item Code>",
      "expiry_date": "<DD/MM/YYYY>",
      "Discount": "<Disc%>",
      "Value": "<Value>",
      "Gst%": "<Gst%>",
      "MRP": "<MRP>",
      "cgst_rate": <CGST Rate>,
      "cgst_amount": <CGST Amount>,
      "sgst_rate": <SGST Rate>,
      "sgst_amount": <SGST Amount>,
      "igst_rate": <IGST Rate>,
      "igst_amount": <IGST Amount>,
      "GST_AMT": "<GST AMT>",
      "taxable_value": <Taxable Value>
    }
  ],
  "uncertain_fields": []
}"""
