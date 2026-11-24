"""
FinGroww Trading Intelligence — Indian Brokers Subsystem.
=========================================================
Exports BrokerManager and all supported broker adapters:
- Zerodha Kite Connect v3
- Angel One SmartAPI
- DhanHQ v2
"""

from .base_broker import BaseBrokerClient
from .zerodha_kite import ZerodhaKiteClient
from .angel_smartapi import AngelSmartApiClient
from .dhan_hq import DhanHqClient
from .broker_manager import BrokerManager, broker_manager

__all__ = [
    "BaseBrokerClient",
    "ZerodhaKiteClient",
    "AngelSmartApiClient",
    "DhanHqClient",
    "BrokerManager",
    "broker_manager",
]
