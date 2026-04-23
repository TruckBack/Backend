from __future__ import annotations

import asyncio
from functools import lru_cache

import boto3
from botocore.client import Config

from app.core.config import settings


@lru_cache(maxsize=1)
def _s3_client():
    return boto3.client(
        "s3",
        region_name=settings.AWS_REGION,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID or None,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY or None,
        config=Config(signature_version="s3v4"),
    )


async def generate_presigned_put_url(
    *, key: str, content_type: str, expires_in: int | None = None
) -> str:
    expires = expires_in or settings.S3_PRESIGNED_EXPIRE_SECONDS

    def _sign() -> str:
        return _s3_client().generate_presigned_url(
            "put_object",
            Params={
                "Bucket": settings.S3_BUCKET,
                "Key": key,
                "ContentType": content_type,
            },
            ExpiresIn=expires,
            HttpMethod="PUT",
        )

    return await asyncio.to_thread(_sign)


def public_object_url(key: str) -> str:
    return f"https://{settings.S3_BUCKET}.s3.{settings.AWS_REGION}.amazonaws.com/{key}"
