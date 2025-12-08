"""
Yahoo Finance extraction schemas.
Split into smaller models for reduced token usage.
"""
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


class YahooQuotePrices(BaseModel):
    """Price-related fields from Yahoo Finance quote."""

    model_config = ConfigDict(populate_by_name=True)

    last_price: Optional[float] = Field(default=None, alias="lastPrice")
    change_abs: Optional[float] = Field(default=None, alias="changeAbs")
    change_pct: Optional[float] = Field(default=None, alias="changePct")
    previous_close: Optional[float] = Field(default=None, alias="previousClose")


class YahooQuoteVolume(BaseModel):
    """Volume-related fields from Yahoo Finance quote."""

    model_config = ConfigDict(populate_by_name=True)

    volume: Optional[int] = None
    avg_volume: Optional[int] = Field(default=None, alias="avgVolume")


class YahooQuoteSnapshot(BaseModel):
    """
    Full structured snapshot of the Yahoo Finance quote panel.
    Kept for backwards compatibility.
    """

    model_config = ConfigDict(populate_by_name=True)

    ticker: str

    # Regular session
    last_price: Optional[float] = Field(default=None, alias="lastPrice")
    change_abs: Optional[float] = Field(default=None, alias="changeAbs")
    change_pct: Optional[float] = Field(default=None, alias="changePct")

    currency: Optional[str] = None

    open_price: Optional[float] = Field(default=None, alias="openPrice")
    previous_close: Optional[float] = Field(default=None, alias="previousClose")

    day_low: Optional[float] = Field(default=None, alias="dayLow")
    day_high: Optional[float] = Field(default=None, alias="dayHigh")

    volume: Optional[int] = None
    avg_volume: Optional[int] = Field(default=None, alias="avgVolume")

    # Extended-hours session
    premarket_change_pct: Optional[float] = None
    after_hours_change_pct: Optional[float] = None
