"""Gemini access. Provider settings and API keys live in the ai_providers collection."""
import json
import logging

from flask import current_app
from google import genai
from google.genai import types

from ..core import ApiError, db

log = logging.getLogger(__name__)


def default_provider():
    provider = db().ai_providers.find_one({"isDefault": True, "isActive": True})
    if not provider:
        raise ApiError(404, "No active AI Provider found.")
    return provider


def _provider(name=None):
    if not name:
        return default_provider()
    provider = db().ai_providers.find_one({"provider": name, "isActive": True})
    if not provider:
        raise ApiError(404, "AI Provider not found.")
    return provider


def generate_text(prompt, temperature=None, min_tokens=None, json_mode=False, provider=None,
                  model=None, max_tokens=None, system_prompts=None):
    settings = _provider(provider)
    if settings["provider"] != "gemini":
        raise ApiError(400, f"Provider {settings['provider']} is not implemented.")
    token_limit = max_tokens or settings.get("maxTokens") or 4096
    if min_tokens:
        token_limit = max(token_limit, min_tokens)
    temp = settings.get("temperature", 0.7) if temperature is None else temperature
    model_name = model or settings.get("modelName") or "gemini-2.5-pro"
    config = types.GenerateContentConfig(
        temperature=temp,
        max_output_tokens=token_limit,
        system_instruction="\n".join(system_prompts) if system_prompts else None,
        response_mime_type="application/json" if json_mode else None,
    )
    try:
        response = genai.Client(api_key=settings["apiKey"]).models.generate_content(
            model=model_name, contents=prompt, config=config
        )
    except Exception as err:
        log.exception("Gemini text request failed")
        raise ApiError(502, "The AI service request failed.") from err
    candidates = response.candidates or []
    finish = candidates[0].finish_reason if candidates else None
    return {
        "success": True,
        "provider": "gemini",
        "modelName": model_name,
        "text": response.text or "",
        "finishReason": getattr(finish, "name", None) or (str(finish) if finish else None),
    }


def generate_json(prompt, temperature=None, min_tokens=None):
    result = generate_text(prompt, temperature=temperature, min_tokens=min_tokens, json_mode=True)
    if result["finishReason"] == "MAX_TOKENS":
        raise ApiError(502, "The AI response was cut off before it finished. Please try again.")
    return parse_json(result["text"])


def parse_json(text):
    cleaned = (text or "").replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(cleaned)
    except ValueError as err:
        log.error("Invalid AI JSON: %s", cleaned[:500])
        raise ApiError(502, "AI returned invalid JSON. Please try again.") from err


def generate_image(prompt):
    settings = default_provider()
    try:
        response = genai.Client(api_key=settings["apiKey"]).models.generate_content(
            model=current_app.config["GEMINI_IMAGE_MODEL"],
            contents=prompt,
            config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
        )
    except Exception as err:
        log.exception("Gemini image request failed")
        raise ApiError(502, "The AI image request failed.") from err
    candidates = response.candidates or []
    parts = candidates[0].content.parts if candidates and candidates[0].content else []
    for part in parts or []:
        if part.inline_data and part.inline_data.data:
            return part.inline_data.data
    raise ApiError(502, "The AI service did not return an image.")
