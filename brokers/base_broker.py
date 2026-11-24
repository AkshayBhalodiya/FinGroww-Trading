"""
FinGroww Trading Intelligence — Unified Broker Integration Layer.
=================================================================
Abstract base class defining the standardized broker API contracts.
Supports Zerodha Kite Connect, Angel One SmartAPI, and DhanHQ.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Tuple, List, Optional
import logging
import time

logger = logging.getLogger("FinGroww.Broker")


class BaseBrokerClient(ABC):
    """Abstract interface for all Indian discount & full-service brokers."""

    def __init__(self, broker_name: str):
        self.broker_name = broker_name
        self.is_connected = False
        self.client_id = ""
        self.user_name = ""
        self.connected_at: Optional[float] = None
        self.credentials: Dict[str, Any] = {}

    @abstractmethod
    def authenticate(self, credentials: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Validates API keys/tokens and logs into broker API.
        Returns: (success: bool, message: str, profile_data: dict)
        """
        pass

    @abstractmethod
    def get_funds(self) -> Tuple[bool, Dict[str, Any], str]:
        """
        Fetches live available margins, cash, and collateral.
        Returns: (success: bool, funds_dict: dict, error_message: str)
        funds_dict schema: {
            "available_cash": float,
            "used_margin": float,
            "total_balance": float,
            "collateral": float,
            "currency": "INR"
        }
        """
        pass

    @abstractmethod
    def get_positions(self) -> Tuple[bool, List[Dict[str, Any]], str]:
        """
        Fetches live real open positions from the broker terminal.
        Returns: (success: bool, positions_list: list, error_message: str)
        """
        pass

    @abstractmethod
    def get_orders(self) -> Tuple[bool, List[Dict[str, Any]], str]:
        """
        Fetches today's orders (Open, Completed, Rejected).
        Returns: (success: bool, orders_list: list, error_message: str)
        """
        pass

    @abstractmethod
    def place_order(
        self,
        symbol: str,
        quantity: int,
        side: str,  # "BUY" or "SELL"
        order_type: str = "MARKET",  # "MARKET", "LIMIT", "SL", "SL-M"
        price: float = 0.0,
        trigger_price: float = 0.0,
        product: str = "MIS",  # "MIS" (Intraday) or "CNC" (Delivery) or "NRML"
        exchange: str = "NSE",
        tag: str = "FINGROWW_ALGO",
        stop_loss: Optional[float] = None,
        target_price: Optional[float] = None,
    ) -> Tuple[bool, Dict[str, Any], str]:
        """
        Executes a real trade on exchange through broker API.
        Returns: (success: bool, order_result: dict, error_message: str)
        """
        pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> Tuple[bool, str]:
        """Cancels an open/pending order."""
        pass

    @abstractmethod
    def square_off_all(self) -> Tuple[bool, int, List[str]]:
        """
        Panic Emergency Circuit Breaker: Closes all real broker open positions.
        Returns: (success: bool, closed_count: int, messages: list)
        """
        pass

    def get_status(self) -> Dict[str, Any]:
        """Returns standard connection status summary."""
        return {
            "broker_name": self.broker_name,
            "is_connected": self.is_connected,
            "client_id": self.client_id,
            "user_name": self.user_name,
            "connected_at": self.connected_at,
            "connected_duration_mins": round((time.time() - self.connected_at) / 60, 1) if self.connected_at else 0.0,
        }
