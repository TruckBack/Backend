"""Gemini AI pricing service.

Calls the Gemini REST API directly via httpx so no extra SDK package is needed.
The module-level ``_call_gemini`` function is importable for test patching.
"""
from __future__ import annotations

import httpx

from app.core.config import settings
from app.core.exceptions import BadRequestError, InternalServerError

_GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-3.1-flash-lite-preview:generateContent"
)

_SYSTEM_PROMPT = (
    "You are a logistics pricing assistant for a delivery platform called TruckBack.\n"
    "Your only job is to estimate a fair market delivery price in USD based on the shipment details the user provides.\n\n"
    "You MUST always respond using EXACTLY this structure — no deviations:\n\n"
    "Price estimate: $X–$Y USD\n"
    "Reason: <one or two sentences explaining the estimate based on the shipment details>\n\n"
    "Strict rules:\n"
    "1. Always respond in English only.\n"
    "2. Always include a specific numeric price range (e.g. $30–$50 USD). Never say 'it depends' without giving a range.\n"
    "3. The reason must be 1–2 sentences maximum — no bullet points, no lists.\n"
    "4. Never ask follow-up questions.\n"
    "5. Never add text outside the two-line structure above (no greetings, no disclaimers, no extra sections).\n"
    "6. If any detail is missing, make a reasonable assumption and factor it into your estimate silently.\n"
)


async def _call_gemini(message: str) -> tuple[int, dict]:
    """POST to the Gemini generateContent endpoint and return (status, json).

    Extracted as a module-level coroutine so tests can patch it without
    touching the entire httpx machinery.
    """
    payload = {
        "system_instruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": message}]}],
        "generationConfig": {"maxOutputTokens": 150, "temperature": 0.1},
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(
            _GEMINI_URL,
            params={"key": settings.GEMINI_API_KEY},
            json=payload,
        )
        return r.status_code, r.json()


async def get_ai_price(message: str) -> str:
    """Call Gemini and return the generated text.

    Raises:
        BadRequestError: when GEMINI_API_KEY is not configured.
        InternalServerError: when Gemini returns an unexpected error.
    """
    if not settings.GEMINI_API_KEY:
        raise BadRequestError("AI pricing is not configured on this server")

    status_code, data = await _call_gemini(message)

    if status_code != 200:
        error_msg = (
            data.get("error", {}).get("message")
            or data.get("error")
            or "Unknown Gemini error"
        )
        raise InternalServerError(f"Gemini API error: {error_msg}")

    try:
        result: str = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise InternalServerError("Unexpected response structure from Gemini") from exc

    return result.strip()
