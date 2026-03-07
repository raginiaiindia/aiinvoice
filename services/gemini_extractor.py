from vertexai.generative_models import GenerativeModel

model = GenerativeModel("gemini-3-pro-preview")

def extract_page(image, prompt):
    response = model.generate_content([prompt, image])
    text = response.text.strip("```").strip()

    if text.lower().startswith("json"):
        text = text[4:].strip()

    return text
