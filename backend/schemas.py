"""
FinGroww SaaS Platform — Pydantic v2 Request/Response Schemas.
Strict typing, email/password validation, and data sanitization contracts.
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, field_validator


# -------------------------------------------------------------------------
# AUTHENTICATION SCHEMAS
# -------------------------------------------------------------------------
class UserRegisterRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=254)
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str = Field(..., min_length=2, max_length=100)
    username: Optional[str] = Field(default=None, min_length=3, max_length=32)
    mobile_number: Optional[str] = Field(default=None, max_length=20)
    experience_level: Literal["beginner", "intermediate", "pro_algo"] = "beginner"
    trading_style: Literal["scalper", "intraday_momentum", "swing_trader", "positional"] = "intraday_momentum"

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        val = v.strip().lower()
        if "@" not in val or "." not in val.split("@")[-1]:
            raise ValueError("Please enter a valid email address")
        return val

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        has_alpha = any(c.isalpha() for c in v)
        has_digit = any(c.isdigit() for c in v)
        if not (has_alpha and has_digit):
            raise ValueError("Password must contain both letters and numbers")
        return v


class UserLoginRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=254)
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class GoogleAuthRequest(BaseModel):
    id_token: str = Field(..., min_length=10)


class EmailVerifyRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=254)
    otp_or_token: str = Field(..., min_length=4, max_length=512)


class ResendVerifyRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=254)


class ForgotPasswordRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=254)


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=10)
    new_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def validate_pw(cls, v: str) -> str:
        if len(v) < 8 or not any(c.isalpha() for c in v) or not any(c.isdigit() for c in v):
            raise ValueError("New password must be at least 8 characters with letters and numbers")
        return v


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(..., min_length=10)


class DeleteAccountRequest(BaseModel):
    password: str = Field(..., min_length=1)
    confirmation_text: str = Field(..., description="Must be 'DELETE'")


# -------------------------------------------------------------------------
# USER PROFILE & PREFERENCES SCHEMAS
# -------------------------------------------------------------------------
class UserPreferencesSchema(BaseModel):
    theme: Literal["dark", "light"] = "dark"
    default_chart_interval: Literal["1m", "5m", "15m", "1h", "1d"] = "15m"
    sound_alerts: bool = True
    email_notifications: bool = True
    telegram_notifications: bool = False
    telegram_chat_id: Optional[str] = None
    daily_loss_limit_pct: float = Field(default=5.0, ge=0.5, le=25.0)


class UserProfileUpdateRequest(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=100)
    username: Optional[str] = Field(default=None, min_length=3, max_length=32)
    mobile_number: Optional[str] = Field(default=None, max_length=20)
    profile_image: Optional[str] = Field(default=None, max_length=500)
    experience_level: Optional[Literal["beginner", "intermediate", "pro_algo"]] = None
    trading_style: Optional[Literal["scalper", "intraday_momentum", "swing_trader", "positional"]] = None
    preferred_timeframe: Optional[Literal["1m", "5m", "15m", "1h", "1d"]] = None
    risk_profile: Optional[Literal["conservative", "moderate", "aggressive"]] = None
    preferences: Optional[UserPreferencesSchema] = None


class UserProfileResponse(BaseModel):
    user_id: str
    email: str
    username: str
    full_name: str
    trading_profile_name: Optional[str] = None
    mobile_number: Optional[str] = None
    profile_image: Optional[str] = None
    role: str
    permissions: List[str] = []
    account_status: str
    is_email_verified: bool
    experience_level: str
    trading_style: str
    preferred_timeframe: str
    risk_profile: str
    subscription_plan: str
    registered_at: str
    last_login_at: Optional[str] = None


class TokenPairResponse(BaseModel):
    ok: bool = True
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int
    user: UserProfileResponse
    verification_otp_dev: Optional[str] = None


# -------------------------------------------------------------------------
# PHASE 2: DASHBOARD, WATCHLISTS, SAVED SIGNALS & NOTIFICATIONS SCHEMAS
# -------------------------------------------------------------------------
class WatchlistAddItemRequest(BaseModel):
    watchlist_name: str = Field(default="Primary Watchlist", min_length=1, max_length=60)
    symbol: str = Field(..., min_length=1, max_length=40)
    alert_above: Optional[float] = Field(default=None, gt=0)
    alert_below: Optional[float] = Field(default=None, gt=0)
    notes: Optional[str] = Field(default=None, max_length=300)


class WatchlistRemoveItemRequest(BaseModel):
    watchlist_name: str = Field(default="Primary Watchlist", min_length=1, max_length=60)
    symbol: str = Field(..., min_length=1, max_length=40)


class SaveSignalRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=40)
    side: Literal["BUY", "SELL", "HOLD"] = "BUY"
    strategy: str = Field(default="15m Confluence", max_length=120)
    entry_price: float = Field(..., gt=0)
    stop_loss: float = Field(..., gt=0)
    target_1: float = Field(..., gt=0)
    target_2: Optional[float] = Field(default=None, gt=0)
    confidence: Optional[float] = Field(default=None, ge=0, le=100)
    rationale: Optional[str] = Field(default=None, max_length=500)


class NotificationReadRequest(BaseModel):
    notification_id: Optional[str] = None
    mark_all: bool = False


# -------------------------------------------------------------------------
# PHASE 3: MULTI-ACCOUNT PAPER TRADING, JOURNAL & AI COACH SCHEMAS
# -------------------------------------------------------------------------
class PaperAccountCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=60)
    virtual_capital: float = Field(default=100000.0, ge=10000.0, le=10000000.0)
    trading_style: Literal["scalper", "intraday_momentum", "swing_trader", "positional"] = "intraday_momentum"


class PaperAccountResetRequest(BaseModel):
    virtual_capital: Optional[float] = Field(default=None, ge=10000.0, le=10000000.0)


class PaperAccountOrderRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=40)
    instrument_type: Literal["EQUITY", "INDEX_FUTURES", "INDEX_OPTIONS", "STOCK_OPTIONS"] = "EQUITY"
    side: Literal["BUY", "SELL"] = "BUY"
    quantity: int = Field(..., ge=1, le=50000)
    entry_price: Optional[float] = Field(default=None, gt=0)
    stop_loss: float = Field(..., gt=0)
    target_1: float = Field(..., gt=0)
    strategy: str = Field(default="Manual Setup", max_length=100)


class PaperAccountCloseRequest(BaseModel):
    position_id: str = Field(..., min_length=4)
    exit_price: Optional[float] = Field(default=None, gt=0)
    exit_reason: str = Field(default="MANUAL_SQUARE_OFF", max_length=60)


class JournalEntryCreateRequest(BaseModel):
    account_id: Optional[str] = None
    trade_id: Optional[str] = None
    symbol: str = Field(..., min_length=1, max_length=40)
    side: Literal["BUY", "SELL"] = "BUY"
    entry_price: Optional[float] = Field(default=None, gt=0)
    exit_price: Optional[float] = Field(default=None, gt=0)
    net_pnl: Optional[float] = None
    timeframe: Literal["1m", "5m", "15m", "1h", "1d"] = "15m"
    setup_tag: str = Field(default="15m Fib Golden Zone", max_length=80)
    mood: Literal["calm", "confident", "disciplined", "fomo", "anxious", "revenge"] = "disciplined"
    rules_followed: bool = True
    mistake_tags: List[str] = Field(default_factory=list, max_length=10)
    notes: str = Field(default="", max_length=3000)


class JournalEntryUpdateRequest(BaseModel):
    setup_tag: Optional[str] = Field(default=None, max_length=80)
    mood: Optional[Literal["calm", "confident", "disciplined", "fomo", "anxious", "revenge"]] = None
    rules_followed: Optional[bool] = None
    mistake_tags: Optional[List[str]] = Field(default=None, max_length=10)
    notes: Optional[str] = Field(default=None, max_length=3000)


# -------------------------------------------------------------------------
# PHASE 4: ADMIN CONTROL CENTRE, MODERATION, AUDIT & SUPPORT SCHEMAS
# -------------------------------------------------------------------------
class AdminUserStatusUpdateRequest(BaseModel):
    account_status: Literal["active", "suspended", "banned"]
    reason: str = Field(default="Administrative review", max_length=300)


class AdminUserRoleUpdateRequest(BaseModel):
    role: Literal["super_admin", "admin", "support", "analyst", "content_manager", "pro_trader", "trader"]


class AdminSubscriptionUpdateRequest(BaseModel):
    plan_code: Literal["free", "pro_algo_swarm", "enterprise"]
    reason: str = Field(default="Admin override", max_length=300)


class FeatureFlagUpdateRequest(BaseModel):
    enabled: bool


class SupportTicketCreateRequest(BaseModel):
    subject: str = Field(..., min_length=3, max_length=150)
    message: str = Field(..., min_length=5, max_length=3000)
    priority: Literal["low", "medium", "urgent"] = "medium"
    category: Literal["account", "paper_trading", "billing", "bug_report", "other"] = "other"


class SupportTicketReplyRequest(BaseModel):
    reply_message: str = Field(..., min_length=2, max_length=3000)
    status: Optional[Literal["open", "investigating", "resolved"]] = None


# -------------------------------------------------------------------------
# PHASE 5: SUBSCRIPTIONS, BILLING WEBHOOKS & ACADEMY LMS SCHEMAS
# -------------------------------------------------------------------------
class SubscriptionCheckoutRequest(BaseModel):
    plan_code: Literal["pro_algo_swarm", "enterprise"] = "pro_algo_swarm"
    billing_cycle: Literal["monthly", "annual"] = "monthly"


class PaymentWebhookPayload(BaseModel):
    event: Literal["payment.captured", "payment.failed"]
    payment_id: str = Field(..., min_length=4, max_length=80)
    user_id: str = Field(..., min_length=4, max_length=80)
    plan_code: Literal["pro_algo_swarm", "enterprise"] = "pro_algo_swarm"
    amount_inr: float = Field(..., gt=0)
    gateway_ref: Optional[str] = None


class AcademyProgressUpdateRequest(BaseModel):
    course_id: str = Field(..., min_length=4, max_length=40)
    lesson_id: str = Field(..., min_length=2, max_length=40)
    quiz_score_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0)




