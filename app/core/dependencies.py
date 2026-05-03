from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import TokenType, decode_token
from app.db.session import get_db
from app.models.user import User, UserRole
from app.repositories.user import UserRepository

http_bearer = HTTPBearer(auto_error=False)

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(http_bearer)],
) -> User:
    token = credentials.credentials if credentials else None
    if not token:
        raise UnauthorizedError("Missing authentication token")
    payload = decode_token(token, expected_type=TokenType.ACCESS)
    try:
        user_id = int(payload["sub"])
    except (TypeError, ValueError) as exc:
        raise UnauthorizedError("Invalid token subject") from exc

    user = await UserRepository(db).get_by_id(user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("User not found or inactive")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(*roles: UserRole):
    async def _checker(user: CurrentUser) -> User:
        if user.role not in roles:
            raise ForbiddenError(f"Requires role(s): {', '.join(r.value for r in roles)}")
        return user

    return _checker


CurrentCustomer = Annotated[User, Depends(require_role(UserRole.CUSTOMER))]
CurrentDriver = Annotated[User, Depends(require_role(UserRole.DRIVER))]
