"""
FinGroww SaaS Platform — MongoDB Atlas 24-Collection Manager & Local Fallback Store.
Provides unified Mongo-compatible collection API across MongoDB Atlas and offline JSON fallback.
"""

import copy
import json
import logging
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from backend.config import settings
from backend.security import ROLE_PERMISSIONS

logger = logging.getLogger("FinGroww.Database")

# Official 24+ Collection Registry
COLLECTION_NAMES = [
    "users",
    "sessions",
    "login_history",
    "roles",
    "permissions",
    "preferences",
    "watchlists",
    "subscriptions",
    "plans",
    "payments",
    "invoices",
    "paper_accounts",
    "paper_orders",
    "paper_positions",
    "paper_trades",
    "trading_journals",
    "signals",
    "signal_outcomes",
    "saved_signals",
    "strategies",
    "strategy_runs",
    "academy_courses",
    "academy_progress",
    "notifications",
    "support_tickets",
    "audit_logs",
    "feature_flags",
]


def _match_filter(doc: Dict[str, Any], filt: Optional[Dict[str, Any]]) -> bool:
    if not filt:
        return True
    for k, v in filt.items():
        if k == "$or":
            if not any(_match_filter(doc, sub) for sub in v):
                return False
            continue
        if k == "$and":
            if not all(_match_filter(doc, sub) for sub in v):
                return False
            continue

        doc_val = doc.get(k)
        if isinstance(v, dict):
            for op, target in v.items():
                if op == "$in":
                    if doc_val not in target:
                        return False
                elif op == "$nin":
                    if doc_val in target:
                        return False
                elif op == "$ne":
                    if doc_val == target:
                        return False
                elif op == "$gt":
                    if doc_val is None or doc_val <= target:
                        return False
                elif op == "$gte":
                    if doc_val is None or doc_val < target:
                        return False
                elif op == "$lt":
                    if doc_val is None or doc_val >= target:
                        return False
                elif op == "$lte":
                    if doc_val is None or doc_val > target:
                        return False
                elif op == "$regex":
                    flags = re.IGNORECASE if v.get("$options", "") == "i" else 0
                    if not doc_val or not re.search(target, str(doc_val), flags):
                        return False
                elif op == "$options":
                    continue
        else:
            if doc_val != v:
                return False
    return True


def _apply_projection(doc: Dict[str, Any], projection: Optional[Dict[str, int]]) -> Dict[str, Any]:
    out = copy.deepcopy(doc)
    if not projection:
        return out
    excludes = {k for k, v in projection.items() if v == 0}
    includes = {k for k, v in projection.items() if v == 1}
    if includes:
        res = {k: out[k] for k in includes if k in out}
        if "_id" in out and "_id" not in excludes:
            res["_id"] = out["_id"]
        return res
    for k in excludes:
        out.pop(k, None)
    return out


class LocalCursor:
    def __init__(self, docs: List[Dict[str, Any]], projection: Optional[Dict[str, int]] = None):
        self._docs = docs
        self._projection = projection

    def sort(self, key_or_list: Any, direction: int = 1):
        if isinstance(key_or_list, list):
            for key, dir_val in reversed(key_or_list):
                self._docs.sort(key=lambda d: str(d.get(key) or ""), reverse=(dir_val < 0))
        elif isinstance(key_or_list, str):
            self._docs.sort(key=lambda d: str(d.get(key_or_list) or ""), reverse=(direction < 0))
        return self

    def skip(self, count: int):
        self._docs = self._docs[count:]
        return self

    def limit(self, count: int):
        if count > 0:
            self._docs = self._docs[:count]
        return self

    def __iter__(self):
        for doc in self._docs:
            yield _apply_projection(doc, self._projection)


class InsertResult:
    def __init__(self, inserted_id: Any):
        self.inserted_id = inserted_id


class UpdateResult:
    def __init__(self, matched_count: int, modified_count: int):
        self.matched_count = matched_count
        self.modified_count = modified_count


class DeleteResult:
    def __init__(self, deleted_count: int):
        self.deleted_count = deleted_count


class LocalCollection:
    """Thread-safe local in-memory/JSON collection mimicking PyMongo Collection API."""

    def __init__(self, name: str, store_ref: Dict[str, List[Dict[str, Any]]], save_cb=None):
        self.name = name
        self._store_ref = store_ref
        self._save_cb = save_cb
        self._lock = threading.RLock()
        self._unique_fields: List[Tuple[str, ...]] = []

    def _docs(self) -> List[Dict[str, Any]]:
        return self._store_ref.setdefault(self.name, [])

    def create_index(self, keys: Any, unique: bool = False, **kwargs):
        if unique:
            if isinstance(keys, str):
                self._unique_fields.append((keys,))
            elif isinstance(keys, list):
                self._unique_fields.append(tuple(k for k, _ in keys))

    def find_one(self, filt: Optional[Dict[str, Any]] = None, projection: Optional[Dict[str, int]] = None) -> Optional[Dict[str, Any]]:
        with self._lock:
            for d in self._docs():
                if _match_filter(d, filt):
                    return _apply_projection(d, projection)
            return None

    def find(self, filt: Optional[Dict[str, Any]] = None, projection: Optional[Dict[str, int]] = None) -> LocalCursor:
        with self._lock:
            matched = [copy.deepcopy(d) for d in self._docs() if _match_filter(d, filt)]
            return LocalCursor(matched, projection)

    def count_documents(self, filt: Optional[Dict[str, Any]] = None) -> int:
        with self._lock:
            return sum(1 for d in self._docs() if _match_filter(d, filt))

    def insert_one(self, doc: Dict[str, Any]) -> InsertResult:
        with self._lock:
            new_doc = copy.deepcopy(doc)
            if "_id" not in new_doc:
                new_doc["_id"] = str(uuid.uuid4())
            docs = self._docs()
            for ufields in self._unique_fields:
                check = {f: new_doc.get(f) for f in ufields if new_doc.get(f) is not None}
                if check and len(check) == len(ufields):
                    for existing in docs:
                        if all(existing.get(f) == val for f, val in check.items()):
                            raise ValueError(f"Duplicate key violation on {self.name}: {ufields}")
            docs.append(new_doc)
            if self._save_cb:
                self._save_cb()
            return InsertResult(new_doc["_id"])

    def update_one(self, filt: Dict[str, Any], update: Dict[str, Any], upsert: bool = False) -> UpdateResult:
        with self._lock:
            docs = self._docs()
            for i, d in enumerate(docs):
                if _match_filter(d, filt):
                    self._apply_update(docs[i], update)
                    if self._save_cb:
                        self._save_cb()
                    return UpdateResult(1, 1)
            if upsert:
                new_doc = {k: v for k, v in filt.items() if not str(k).startswith("$")}
                self._apply_update(new_doc, update)
                new_doc.setdefault("_id", str(uuid.uuid4()))
                docs.append(new_doc)
                if self._save_cb:
                    self._save_cb()
                return UpdateResult(0, 1)
            return UpdateResult(0, 0)

    def update_many(self, filt: Dict[str, Any], update: Dict[str, Any]) -> UpdateResult:
        with self._lock:
            docs = self._docs()
            count = 0
            for i, d in enumerate(docs):
                if _match_filter(d, filt):
                    self._apply_update(docs[i], update)
                    count += 1
            if count and self._save_cb:
                self._save_cb()
            return UpdateResult(count, count)

    def delete_one(self, filt: Dict[str, Any]) -> DeleteResult:
        with self._lock:
            docs = self._docs()
            for i, d in enumerate(docs):
                if _match_filter(d, filt):
                    docs.pop(i)
                    if self._save_cb:
                        self._save_cb()
                    return DeleteResult(1)
            return DeleteResult(0)

    def delete_many(self, filt: Dict[str, Any]) -> DeleteResult:
        with self._lock:
            docs = self._docs()
            before = len(docs)
            self._store_ref[self.name] = [d for d in docs if not _match_filter(d, filt)]
            deleted = before - len(self._store_ref[self.name])
            if deleted and self._save_cb:
                self._save_cb()
            return DeleteResult(deleted)

    @staticmethod
    def _apply_update(doc: Dict[str, Any], update: Dict[str, Any]):
        if "$set" in update:
            for k, v in update["$set"].items():
                doc[k] = copy.deepcopy(v)
        if "$inc" in update:
            for k, v in update["$inc"].items():
                doc[k] = (doc.get(k) or 0) + v
        if "$push" in update:
            for k, v in update["$push"].items():
                arr = doc.setdefault(k, [])
                if isinstance(arr, list):
                    arr.append(copy.deepcopy(v))
        if "$setOnInsert" in update and "_id" not in doc:
            for k, v in update["$setOnInsert"].items():
                doc.setdefault(k, copy.deepcopy(v))


class DatabaseManager:
    """
    Central database manager supporting MongoDB Atlas with automatic index setup
    and seamless local file fallback when Atlas URI is unavailable.
    """

    def __init__(self, local_store_path: str = "data/fingroww_v2_store.json"):
        self._lock = threading.RLock()
        self._local_path = local_store_path
        self._local_store: Dict[str, List[Dict[str, Any]]] = {name: [] for name in COLLECTION_NAMES}
        self._mongo_client = None
        self._mongo_db = None
        self.mode = "initializing"
        self._local_collections: Dict[str, LocalCollection] = {}
        self._initialized = False

    def init(self, force_local: bool = False):
        with self._lock:
            if self._initialized and not force_local:
                return
            self._load_local_store()
            uri = settings.MONGODB_URI.strip() if not force_local else ""

            if uri and "<db_username>" not in uri:
                try:
                    from pymongo import MongoClient
                    kwargs: Dict[str, Any] = {
                        "serverSelectionTimeoutMS": 2000,
                        "connectTimeoutMS": 2000,
                        "socketTimeoutMS": 3000,
                        "maxPoolSize": 20,
                    }
                    try:
                        import certifi
                        kwargs["tlsCAFile"] = certifi.where()
                    except Exception:
                        pass
                    client = MongoClient(uri, **kwargs)
                    client.admin.command("ping")
                    self._mongo_client = client
                    self._mongo_db = client[settings.MONGODB_DB_NAME]
                    self.mode = "mongodb_atlas"
                    logger.info("Connected to MongoDB Atlas (%s)", settings.MONGODB_DB_NAME)
                except Exception as exc:
                    logger.warning("MongoDB Atlas unavailable (%s), using resilient local store.", exc)
                    self._mongo_db = None
                    self.mode = "local_fallback"
            else:
                self.mode = "local_fallback"

            self._initialized = True
            self._ensure_indexes()
            self._seed_defaults()

    def _load_local_store(self):
        if os.path.exists(self._local_path):
            try:
                with open(self._local_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    for k in COLLECTION_NAMES:
                        if isinstance(raw.get(k), list):
                            self._local_store[k] = raw[k]
            except Exception as exc:
                logger.warning("Could not load local v2 datastore: %s", exc)

    def _save_local_store(self):
        if self.mode == "mongodb_atlas":
            return
        try:
            parent = os.path.dirname(self._local_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            tmp_path = f"{self._local_path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._local_store, f, default=str)
            os.replace(tmp_path, self._local_path)
        except Exception as exc:
            logger.debug("Local store save deferred: %s", exc)

    def collection(self, name: str):
        if not self._initialized:
            self.init()
        if self._mongo_db is not None:
            return self._mongo_db[name]
        if name not in self._local_collections:
            self._local_collections[name] = LocalCollection(name, self._local_store, self._save_local_store)
        return self._local_collections[name]

    def _ensure_indexes(self):
        """Creates all required unique, compound, and TTL indexes across all 24+ collections."""
        self.collection("users").create_index("email", unique=True)
        self.collection("users").create_index("user_id", unique=True)
        self.collection("users").create_index("username", unique=True)
        self.collection("users").create_index("role")

        self.collection("sessions").create_index("session_id", unique=True)
        self.collection("sessions").create_index([("user_id", 1), ("is_revoked", 1)])
        self.collection("sessions").create_index("expires_at", expireAfterSeconds=0)

        self.collection("login_history").create_index([("user_id", 1), ("logged_in_at", -1)])
        self.collection("preferences").create_index("user_id", unique=True)
        self.collection("watchlists").create_index([("user_id", 1), ("name", 1)])

        self.collection("plans").create_index("plan_code", unique=True)
        self.collection("subscriptions").create_index([("user_id", 1), ("status", 1)])
        self.collection("payments").create_index("payment_id", unique=True)
        self.collection("invoices").create_index("invoice_id", unique=True)

        self.collection("paper_accounts").create_index("account_id", unique=True)
        self.collection("paper_accounts").create_index("user_id")
        self.collection("paper_orders").create_index([("user_id", 1), ("created_at", -1)])
        self.collection("paper_positions").create_index([("user_id", 1), ("account_id", 1), ("status", 1)])
        self.collection("paper_trades").create_index([("user_id", 1), ("account_id", 1), ("closed_at", -1)])

        self.collection("trading_journals").create_index([("user_id", 1), ("trade_date", -1)])
        self.collection("signals").create_index([("symbol", 1), ("timestamp", -1)])
        self.collection("signal_outcomes").create_index([("signal_id", 1)])
        self.collection("saved_signals").create_index([("user_id", 1), ("saved_at", -1)])
        self.collection("strategies").create_index("strategy_code", unique=True)
        self.collection("strategy_runs").create_index([("user_id", 1), ("created_at", -1)])

        self.collection("academy_courses").create_index("course_id", unique=True)
        self.collection("academy_progress").create_index([("user_id", 1), ("course_id", 1)], unique=True)

        self.collection("notifications").create_index([("user_id", 1), ("is_read", 1), ("created_at", -1)])
        self.collection("support_tickets").create_index([("user_id", 1), ("status", 1)])
        self.collection("audit_logs").create_index([("actor_user_id", 1), ("timestamp", -1)])
        self.collection("feature_flags").create_index("key", unique=True)

    def _seed_defaults(self):
        """Seeds system plans, roles, permissions, and feature flags safely (idempotent)."""
        now_iso = datetime.now(timezone.utc).isoformat()

        # Seed Plans
        plans = self.collection("plans")
        if plans.count_documents({}) == 0:
            plans.insert_one({
                "plan_code": "free",
                "name": "Free AI Paper Trading",
                "price_inr": 0,
                "billing_cycle": "forever",
                "features": [
                    "₹1,00,000 Free Virtual Capital",
                    "Real-time NSE Quotes & Charts",
                    "Dynamic Trailing Stop-Loss",
                    "5% Daily Drawdown Circuit Breaker",
                    "1-Click Paper Trade Simulator",
                ],
                "max_paper_accounts": 1,
                "created_at": now_iso,
            })
            plans.insert_one({
                "plan_code": "pro_algo_swarm",
                "name": "Pro Algo Swarm",
                "price_inr": 1499,
                "billing_cycle": "monthly",
                "features": [
                    "Everything in Free Plan",
                    "4-Agent Autonomous Algo Trading Swarm",
                    "Zerodha, Angel One, Upstox & Dhan Live Webhooks",
                    "Multiple Virtual Paper Accounts",
                    "Exact Entry, SL, Target 1 & Target 2 Guidance",
                    "AI Trading Coach & Journal Analytics",
                    "5-Year Strategy Backtest Engine",
                ],
                "max_paper_accounts": 10,
                "created_at": now_iso,
            })

        # Seed Roles & Permissions
        roles_col = self.collection("roles")
        if roles_col.count_documents({}) == 0:
            for r_name, perms in ROLE_PERMISSIONS.items():
                roles_col.insert_one({
                    "role": r_name,
                    "permissions": sorted(list(perms)),
                    "updated_at": now_iso,
                })

        # Seed Feature Flags
        flags_col = self.collection("feature_flags")
        default_flags = [
            {"key": "enable_google_oauth", "enabled": True, "description": "Allow Sign in with Google"},
            {"key": "enable_email_verification", "enabled": True, "description": "Require email OTP verification"},
            {"key": "enable_multi_paper_accounts", "enabled": True, "description": "Allow multiple paper accounts per user"},
            {"key": "enable_live_broker_execution", "enabled": True, "description": "Allow live broker webhooks for Pro users"},
            {"key": "enable_academy_lms", "enabled": True, "description": "Enable Academy LMS tracking"},
        ]
        for flag in default_flags:
            if not flags_col.find_one({"key": flag["key"]}):
                flags_col.insert_one({**flag, "updated_at": now_iso})

        # Seed 4-Stage Academy LMS Courses
        courses_col = self.collection("academy_courses")
        if courses_col.count_documents({}) == 0:
            courses = [
                {
                    "course_id": "COURSE-01",
                    "stage": 1,
                    "title": "Market Foundations & Capital Preservation",
                    "description": "Master NSE market hours, lot sizing, order types, slippage, and the 5% daily drawdown circuit breaker rule.",
                    "level": "Beginner",
                    "lessons": [
                        {"lesson_id": "L1-1", "title": "How NSE Cash & F&O Lots Work", "duration_mins": 12},
                        {"lesson_id": "L1-2", "title": "Position Sizing & Risk-to-Reward (1:3+ Math)", "duration_mins": 15},
                        {"lesson_id": "L1-3", "title": "Brokerage, STT, Stamp Duty & Slippage Reality", "duration_mins": 10},
                        {"lesson_id": "L1-4", "title": "Eliminating Revenge Trading with Circuit Breakers", "duration_mins": 14},
                    ],
                },
                {
                    "course_id": "COURSE-02",
                    "stage": 2,
                    "title": "15m Fibonacci Golden Zone & Price Action",
                    "description": "High-probability pullback setups combining 0.618 Golden Zone, VWAP institutional flow, and 9/21 EMA alignment.",
                    "level": "Intermediate",
                    "lessons": [
                        {"lesson_id": "L2-1", "title": "1H Macro Trend Confirmation Checklist", "duration_mins": 16},
                        {"lesson_id": "L2-2", "title": "Drawing Institutional 0.618 Fibonacci Zones", "duration_mins": 18},
                        {"lesson_id": "L2-3", "title": "VWAP & Volume Expansion Breakouts", "duration_mins": 14},
                        {"lesson_id": "L2-4", "title": "5M Sniper Entry & Dynamic Trailing Stop-Loss", "duration_mins": 20},
                    ],
                },
                {
                    "course_id": "COURSE-03",
                    "stage": 3,
                    "title": "NSE Option Chain, PCR & Volatility Mastery",
                    "description": "Decode Open Interest concentration, Put-Call Ratio shifts, Theta decay, and strike selection for Nifty & Bank Nifty.",
                    "level": "Intermediate",
                    "lessons": [
                        {"lesson_id": "L3-1", "title": "Reading Call/Put Writing Support & Resistance", "duration_mins": 18},
                        {"lesson_id": "L3-2", "title": "PCR Sentiment & Institutional Flow Analysis", "duration_mins": 15},
                        {"lesson_id": "L3-3", "title": "Avoiding IV Crush & Theta Traps on Expiry", "duration_mins": 16},
                    ],
                },
                {
                    "course_id": "COURSE-04",
                    "stage": 4,
                    "title": "Multi-Agent Algo Swarm & Backtest Validation",
                    "description": "Operate autonomous 4-agent trading pipelines, Monte Carlo backtesting, and secure webhook broker execution.",
                    "level": "Pro Algo",
                    "lessons": [
                        {"lesson_id": "L4-1", "title": "Architecture of Scout, Sentinel, Sniper & Exit Agents", "duration_mins": 20},
                        {"lesson_id": "L4-2", "title": "Validating Strategies Across 5-Year Historical Data", "duration_mins": 22},
                        {"lesson_id": "L4-3", "title": "Safe Webhook Execution on Zerodha, Angel, Upstox & Dhan", "duration_mins": 18},
                    ],
                },
            ]
            for c in courses:
                courses_col.insert_one({**c, "created_at": now_iso})


db_manager = DatabaseManager()
