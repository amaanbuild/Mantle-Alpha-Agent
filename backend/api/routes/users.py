"""User endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.dependencies import db_session
from backend.api.schemas import UserResponse
from backend.database.repositories import UserRepository

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/{user_id}", response_model=UserResponse, summary="Get a user by internal id")
async def get_user(
    user_id: int,
    session: AsyncSession = Depends(db_session),
) -> UserResponse:
    user = await UserRepository(session).get_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return UserResponse.model_validate(user)
