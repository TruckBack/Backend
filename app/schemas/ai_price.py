from __future__ import annotations

from pydantic import BaseModel, Field


class AIPriceRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class AIPriceResponse(BaseModel):
    result: str
