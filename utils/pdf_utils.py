import fitz  # PyMuPDF
from PIL import Image

def pdf_to_images_pymupdf(pdf_path):
    doc = fitz.open(pdf_path)
    images = []

    for page in doc:
        pix = page.get_pixmap(dpi=300)  # HIGH RES = better OCR
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        images.append(img)

    return images
