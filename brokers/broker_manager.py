"""
FinGroww Trading Intelligence — Multi-Broker Session Manager.
============================================================
Coordinates broker connections across multiple user profiles,
enforces credential security, and bridges real broker trades to the execution engine.
"""

import threading
import logging
import time
from typing import Dict, Any, Optional, Tuple, List
from .base_broker import BaseBrokerClient
from .zerodha_kite import ZerodhaKiteClient
from .angel_smartapi import AngelSmartApiClient
from .dhan_hq import DhanHqClient
from .upstox import UpstoxClient

logger = logging.getLogger("FinGroww.BrokerManager")


class BrokerManager:
    """Singleton broker orchestrator managing active user broker sessions."""

    _instance: Optional["BrokerManager"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._clients: Dict[str, BaseBrokerClient] = {}  # {user_name: BaseBrokerClient}
        self._user_modes: Dict[str, str] = {}            # {user_name: "PAPER" | "REAL"}
        self._manager_lock = threading.RLock()

    @classmethod
    def get_instance(cls) -> "BrokerManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = BrokerManager()
            return cls._instance

    def get_client(self, user_name: str) -> Optional[BaseBrokerClient]:
        uname = (user_name or "Akshay").strip()
        with self._manager_lock:
            return self._clients.get(uname)

    def get_trading_mode(self, user_name: str) -> str:
        uname = (user_name or "Akshay").strip()
        with self._manager_lock:
            return self._user_modes.get(uname, "PAPER")

    def set_trading_mode(self, user_name: str, mode: str) -> Tuple[bool, str]:
        uname = (user_name or "Akshay").strip()
        clean_mode = str(mode or "PAPER").upper().strip()
        if clean_mode not in ("PAPER", "REAL"):
            return False, "Invalid trading mode. Must be 'PAPER' or 'REAL'."

        with self._manager_lock:
            client = self._clients.get(uname)
            if clean_mode == "REAL":
                if not client or not client.is_connected:
                    return False, "Cannot switch to REAL mode without an active connected broker (Zerodha, Angel One, Dhan, or Upstox)."
            self._user_modes[uname] = clean_mode
            logger.info("Switched trading mode for [%s] to %s", uname, clean_mode)
            return True, f"Trading mode successfully set to {clean_mode}."

    def connect_broker(
        self,
        user_name: str,
        broker_name: str,
        credentials: Dict[str, Any]
    ) -> Tuple[bool, str, Dict[str, Any]]:
        uname = (user_name or "Akshay").strip()
        b_name = str(broker_name or "").upper().strip()

        client: BaseBrokerClient
        if "ZERODHA" in b_name or "KITE" in b_name:
            client = ZerodhaKiteClient()
        elif "ANGEL" in b_name or "SMARTAPI" in b_name:
            client = AngelSmartApiClient()
        elif "DHAN" in b_name:
            client = DhanHqClient()
        elif "UPSTOX" in b_name:
            client = UpstoxClient()
        else:
            return False, f"Unsupported broker [{broker_name}]. Supported: Zerodha Kite, Angel One, Dhan, Upstox.", {}

        success, msg, profile = client.authenticate(credentials)
        if success:
            with self._manager_lock:
                self._clients[uname] = client
            logger.info("Broker [%s] successfully connected for user [%s]", client.broker_name, uname)
            return True, msg, {
                "broker": client.broker_name,
                "client_id": client.client_id,
                "user_name": client.user_name,
                "connected_at": client.connected_at,
                "profile": profile,
            }
        return False, msg, {}

    def disconnect_broker(self, user_name: str) -> Tuple[bool, str]:
        uname = (user_name or "Akshay").strip()
        with self._manager_lock:
            if uname in self._clients:
                client = self._clients.pop(uname)
                client.is_connected = False
            # Revert mode to PAPER
            self._user_modes[uname] = "PAPER"
        logger.info("Broker disconnected for user [%s]", uname)
        return True, "Broker successfully disconnected. Switched to Paper Trading."

    def get_status(self, user_name: str) -> Dict[str, Any]:
        uname = (user_name or "Akshay").strip()
        with self._manager_lock:
            client = self._clients.get(uname)
            mode = self._user_modes.get(uname, "PAPER")
            if client and client.is_connected:
                status = client.get_status()
                status["mode"] = mode
                return status
            return {
                "broker_name": None,
                "is_connected": False,
                "client_id": None,
                "user_name": None,
                "mode": mode,
            }


broker_manager = BrokerManager.get_instance()
