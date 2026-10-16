"""
apps/asma-service/groq_client.py

Thin wrapper around the Groq chat completions API for structured
JSON extraction. Used by /marketing/brief (and later /content,
/translate, /designer-brief).

Setup:
  1. Get a Groq API key: https://console.groq.com/keys
  2. Add to your .env file (create one from .env.example if you don't
     have it yet, in the repo root):
         GROQ_API_KEY=gsk_your_key_here
  3. pip install httpx  (already in requirements.txt)
"""

import os
import json
import httpx
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-120b"


class GroqClientError(Exception):
    pass


def call_groq_json(system_prompt: str, user_prompt: str, temperature: float = 0.2) -> dict:
    """
    Calls Groq chat completions with JSON mode forced on, and returns
    a parsed Python dict. Raises GroqClientError on any failure so the
    calling endpoint can turn it into a clean HTTP error.
    """
    if os.getenv("MOCK_MODE", "false").lower() == "true":
        # Mock mode fallback to allow offline/local testing
        if "ops assistant" in system_prompt.lower() or "objective" in system_prompt.lower():
            return {
              "objective": {"value": "Weekend Fusion Campaign", "confidence": 0.9},
              "audience": {"value": "Students and families near Staples Mill", "confidence": 0.85},
              "location": {"value": "Staples Mill", "confidence": 0.95},
              "offer": {"value": "Halal Korean-Mexican fusion, weekend offer", "confidence": 0.9},
              "dates": {"value": "Weekend", "confidence": 0.8},
              "deliverables": {"value": "Original food photos only", "confidence": 0.75},
              "platforms": {"value": "Instagram and Facebook", "confidence": 0.9},
              "assets": {"value": "Food photos", "confidence": 0.8},
              "missing_fields": []
            }
        elif "copywriter" in system_prompt.lower() or "caption" in system_prompt.lower():
            return {
                "caption": "Craving some epic flavor? Stop by this weekend for our mouth-watering Halal Korean-Mexican fusion! 🌮🔥 Crafted with original ingredients, it is the perfect meal to share.",
                "cta": "Order now on DoorDash or Uber Eats!"
            }
        elif "translator" in system_prompt.lower() or "roman urdu" in system_prompt.lower() or "translate" in system_prompt.lower():
            return {
                "translated_text": "Kya aap behtareen zaiqe ki talaash mein hain? Is weekend aaiye aur hamare mazedaar Halal Korean-Mexican fusion ka maza lijiye! DoorDash aur Uber Eats par abhi order karein.",
                "ambiguous_terms": []
            }
        elif "designer-brief" in system_prompt.lower() or "visual" in system_prompt.lower() or "designer" in system_prompt.lower():
            return {
              "main_heading": "WEEKEND FUSION",
              "supporting_text": "Halal Korean-Mexican flavor delivered with DoorDash and Uber Eats.",
              "visual_direction": "Vibrant and warm radial gradient background. Highlighting delicious fusion food images.",
              "sizes": ["1080x1350 Portrait", "1200x630 Landscape"],
              "logo_qr_rules": "Logo locked in top-left, QR code in bottom-right.",
              "restrictions": "No copyright images; use royalty-free or brand-approved assets only."
            }
        elif "reviewer" in system_prompt.lower() or "revise" in system_prompt.lower():
            return {
                "revised_caption": "Enjoy our delicious weekend special in Lahore!",
                "revised_cta": "Order today!"
            }
        else:
            return {}

    if not GROQ_API_KEY:
        raise GroqClientError("GROQ_API_KEY is not set in environment configurations.")

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    body = {
        "model": GROQ_MODEL,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(GROQ_API_URL, headers=headers, json=body)
            response.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise GroqClientError(f"Groq API returned {e.response.status_code}: {e.response.text}")
    except httpx.RequestError as e:
        raise GroqClientError(f"Groq API request failed: {e}")

    data = response.json()

    try:
        raw_content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        raise GroqClientError(f"Unexpected Groq response shape: {data}")

    try:
        return json.loads(raw_content)
    except json.JSONDecodeError:
        raise GroqClientError(f"Groq did not return valid JSON: {raw_content}")