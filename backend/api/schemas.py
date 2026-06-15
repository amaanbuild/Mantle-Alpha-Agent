"""
Pydantic request/response schemas for the REST API.

Kept separate from ORM models so the wire contract can evolve independently and
OpenAPI docs stay clean. ``from_attributes=True`` lets us build responses
directly from ORM rows.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from backend.core.types import EventType


# --------------------------------------------------------------------------- #
# Health / status                                                              #
# --------------------------------------------------------------------------- #
class HealthResponse(BaseModel):
    status: str = "ok"
    app: str
    version: str
    environment: str
    database: bool
    rpc: bool


# --------------------------------------------------------------------------- #
# Users                                                                        #
# --------------------------------------------------------------------------- #
class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    telegram_id: int
    username: str | None = None
    first_name: str | None = None
    is_active: bool
    notifications_enabled: bool
    created_at: datetime


# --------------------------------------------------------------------------- #
# Alert rules                                                                  #
# --------------------------------------------------------------------------- #
class AlertRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    token_symbol: str
    token_address: str | None = None
    event_type: EventType
    threshold_usd: float
    is_active: bool
    created_at: datetime


class CreateAlertRequest(BaseModel):
    telegram_id: int = Field(..., description="Telegram id of the owning user.")
    chat_id: int | None = Field(
        default=None, description="Chat id for delivery (defaults to telegram_id)."
    )
    token: str = Field(..., examples=["mETH", "MNT"])
    threshold_usd: float = Field(..., gt=0, examples=[10000])
    event_type: EventType = Field(default=EventType.ANY)


# --------------------------------------------------------------------------- #
# Alert history                                                                #
# --------------------------------------------------------------------------- #
class AlertHistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    rule_id: int | None = None
    token_symbol: str
    event_type: EventType
    direction: str | None = None
    tx_hash: str
    from_address: str | None = None
    to_address: str | None = None
    value_usd: float
    token_price_usd: float | None = None
    insight: str | None = None
    status: str
    created_at: datetime


class MessageResponse(BaseModel):
    message: str
