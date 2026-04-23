from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ConflictError, UnauthorizedError
from app.core.security import (
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.driver import Driver, DriverStatus
from app.models.user import User, UserRole
from app.repositories.driver import DriverRepository
from app.repositories.user import UserRepository
from app.schemas.auth import CustomerRegister, DriverRegister, TokenResponse


class AuthService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.users = UserRepository(db)
        self.drivers = DriverRepository(db)

    async def register_customer(self, data: CustomerRegister) -> User:
        if await self.users.get_by_email(data.email):
            raise ConflictError("Email already registered")
        user = User(
            email=data.email.lower(),
            hashed_password=hash_password(data.password),
            full_name=data.full_name,
            phone=data.phone,
            role=UserRole.CUSTOMER,
        )
        await self.users.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def register_driver(self, data: DriverRegister) -> User:
        if await self.users.get_by_email(data.email):
            raise ConflictError("Email already registered")
        if await self.drivers.get_by_license(data.license_number):
            raise ConflictError("License number already registered")

        user = User(
            email=data.email.lower(),
            hashed_password=hash_password(data.password),
            full_name=data.full_name,
            phone=data.phone,
            role=UserRole.DRIVER,
        )
        await self.users.add(user)

        driver = Driver(
            user_id=user.id,
            license_number=data.license_number,
            vehicle_type=data.vehicle_type,
            vehicle_plate=data.vehicle_plate,
            vehicle_capacity_kg=data.vehicle_capacity_kg,
            status=DriverStatus.OFFLINE,
        )
        await self.drivers.add(driver)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def authenticate(self, email: str, password: str) -> User:
        user = await self.users.get_by_email(email)
        if not user or not verify_password(password, user.hashed_password):
            raise UnauthorizedError("Invalid credentials")
        if not user.is_active:
            raise UnauthorizedError("Account is disabled")
        return user

    @staticmethod
    def issue_tokens(user: User) -> TokenResponse:
        access = create_access_token(user.id, role=user.role.value)
        refresh = create_refresh_token(user.id)
        return TokenResponse(
            access_token=access,
            refresh_token=refresh,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    async def refresh(self, refresh_token: str) -> TokenResponse:
        payload = decode_token(refresh_token, expected_type=TokenType.REFRESH)
        try:
            user_id = int(payload["sub"])
        except (TypeError, ValueError) as exc:
            raise UnauthorizedError("Invalid token subject") from exc
        user = await self.users.get_by_id(user_id)
        if not user or not user.is_active:
            raise UnauthorizedError("User not found or inactive")
        return self.issue_tokens(user)
