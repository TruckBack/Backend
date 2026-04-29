from __future__ import annotations

from fastapi import APIRouter

from app.core.dependencies import CurrentUser
from app.schemas.ai_price import AIPriceRequest, AIPriceResponse
from app.services.ai_price import get_ai_price

router = APIRouter(prefix="/aiprice", tags=["ai"])


@router.post("", response_model=AIPriceResponse)
async def ai_price(
    payload: AIPriceRequest,
    _: CurrentUser,  # auth only — user identity not needed for the AI call
) -> AIPriceResponse:
    """Call Gemini to estimate a delivery price from the provided message.

    Requires a valid JWT. Returns ``{ "result": "<price estimate>" }``.
    """
    result = await get_ai_price(payload.message)
    return AIPriceResponse(result=result)
