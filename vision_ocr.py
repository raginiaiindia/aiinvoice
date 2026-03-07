from google.cloud import vision
from pdf2image import convert_from_path
import io
import os

client = vision.ImageAnnotatorClient()

def extract_text_from_image(image_path):
    with io.open(image_path, "rb") as f:
        content = f.read()

    image = vision.Image(content=content)
    response = client.document_text_detection(image=image)

    if response.error.message:
        raise Exception(response.error.message)

    return response.full_text_annotation.text


def extract_text_from_pdf(pdf_path):
    images = convert_from_path(pdf_path, dpi=300)
    full_text = ""

    for img in images:
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")

        image = vision.Image(content=img_bytes.getvalue())
        response = client.document_text_detection(image=image)

        if response.error.message:
            raise Exception(response.error.message)

        full_text += response.full_text_annotation.text + "\n"

    return full_text
