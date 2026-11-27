"""
FinGroww SaaS Platform — Cryptographic Security, JWT Engine, Rate Limiting & RBAC.
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Set, Tuple

from backend.config import settings


# -------------------------------------------------------------------------
# ROLE-BASED ACCESS CONTROL (RBAC) MATRIX
# -------------------------------------------------------------------------
ROLE_PERMISSIONS: Dict[str, Set[str]] = {
    "super_admin": {
        "admin:*",
        "users:read",
        "users:write",
        "users:suspend",
        "users:delete",
        "roles:assign",
        "revenue:read",
        "audit:read",
        "tickets:manage",
        "content:manage",
        "paper:trade",
        "paper:multi_account",
        "broker:live_execute",
        "scanner:pro",
        "journal:write",
    },
    "admin": {
        "users:read",
        "users:write",
        "users:suspend",
        "revenue:read",
        "audit:read",
        "tickets:manage",
        "content:manage",
        "paper:trade",
        "paper:multi_account",
        "scanner:pro",
        "journal:write",
    },
    "support": {
        "users:read",
        "tickets:manage",
        "paper:trade",
        "journal:write",
    },
    "analyst": {
        "signals:publish",
        "scanner:pro",
        "paper:trade",
        "journal:write",
        "audit:read",
    },
    "content_manager": {
        "content:manage",
        "academy:publish",
        "paper:trade",
        "journal:write",
    },
    "pro_trader": {
        "paper:trade",
        "paper:multi_account",
        "broker:live_execute",
        "scanner:pro",
        "journal:write",
    },
    "trader": {
        "paper:trade",
        "journal:write",
    },
}


def get_role_permissions(role: str) -> Set[str]:
    return ROLE_PERMISSIONS.get((role or "trader").lower(), ROLE_PERMISSIONS["trader"])


def has_permission(role: str, required_perm: str) -> bool:
    perms = get_role_permissions(role)
    if "admin:*" in perms:
        return True
    return required_perm in perms


# -------------------------------------------------------------------------
# SALTED SCRYPT PASSWORD HASHING (WITH LEGACY SHA-256 VERIFICATION BRIDGE)
# -------------------------------------------------------------------------
def hash_password(password: str) -> str:
    """Hashes a plaintext password using memory-hard scrypt with 16-byte random salt."""
    if not password:
        raise ValueError("Password cannot be empty")
    salt = os.urandom(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=16384,
        r=8,
        p=1,
        dklen=32,
    )
    salt_b64 = base64.urlsafe_b64encode(salt).decode("ascii")
    hash_b64 = base64.urlsafe_b64encode(derived).decode("ascii")
    return f"scrypt$16384$8$1${salt_b64}${hash_b64}"


def verify_password(password: str, stored_hash: str) -> Tuple[bool, bool]:
    """
    Verifies a password against stored hash.
    Returns (is_valid, needs_rehash_to_scrypt).
    Supports modern scrypt hashes and transparently handles legacy SHA-256 hashes for zero-break migration.
    """
    if not password or not stored_hash:
        return False, False

    if stored_hash.startswith("scrypt$"):
        try:
            parts = stored_hash.split("$")
            if len(parts) != 6:
                return False, False
            _, n_str, r_str, p_str, salt_b64, expected_b64 = parts
            salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
            expected = base64.urlsafe_b64decode(expected_b64.encode("ascii"))
            derived = hashlib.scrypt(
                password.encode("utf-8"),
                salt=salt,
                n=int(n_str),
                r=int(r_str),
                p=int(p_str),
                dklen=len(expected),
            )
            return hmac.compare_digest(derived, expected), False
        except Exception:
            return False, False

    # Legacy SHA-256 fallback (flag needs_rehash=True so login transparently upgrades it!)
    if len(stored_hash) == 64:
        legacy_sha = hashlib.sha256(password.encode("utf-8")).hexdigest()
        is_match = hmac.compare_digest(legacy_sha, stored_hash)
        return is_match, is_match

    return False, False


# -------------------------------------------------------------------------
# RFC 7519 HS256 JWT ENGINE (ZERO EXTERNAL BINARY DEPENDENCIES)
# -------------------------------------------------------------------------
def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    padding = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode((s + padding).encode("ascii"))


def encode_jwt(payload: Dict[str, Any], secret: Optional[str] = None) -> str:
    key = (secret or settings.JWT_SECRET_KEY).encode("utf-8")
    header = {"alg": "HS256", "typ": "JWT"}
    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    sig = hmac.new(key, signing_input, hashlib.sha256).digest()
    return f"{header_b64}.{payload_b64}.{_b64url_encode(sig)}"


def decode_jwt(token: str, expected_type: Optional[str] = None, secret: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if not token or not isinstance(token, str):
        return None
    parts = token.strip().split(".")
    if len(parts) != 3:
        return None
    header_b64, payload_b64, sig_b64 = parts
    try:
        key = (secret or settings.JWT_SECRET_KEY).encode("utf-8")
        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        expected_sig = hmac.new(key, signing_input, hashlib.sha256).digest()
        provided_sig = _b64url_decode(sig_b64)
        if not hmac.compare_digest(expected_sig, provided_sig):
            return None

        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
        exp = payload.get("exp")
        if exp is None or float(exp) < time.time():
            return None
        if expected_type and payload.get("token_type") != expected_type:
            return None
        return payload
    except Exception:
        return None


def create_access_token(user_id: str, email: str, role: str, session_id: str, username: str) -> str:
    now = int(time.time())
    exp = now + (settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60)
    payload = {
        "sub": user_id,
        "email": email,
        "username": username,
        "role": role,
        "sid": session_id,
        "jti": secrets.token_hex(12),
        "token_type": "access",
        "iat": now,
        "exp": exp,
    }
    return encode_jwt(payload)


def create_refresh_token(user_id: str, session_id: str) -> Tuple[str, str]:
    now = int(time.time())
    exp = now + (settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400)
    jti = secrets.token_hex(16)
    payload = {
        "sub": user_id,
        "sid": session_id,
        "jti": jti,
        "token_type": "refresh",
        "iat": now,
        "exp": exp,
    }
    return encode_jwt(payload), jti


def create_action_token(user_id: str, email: str, action: str, expires_seconds: int) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "email": email,
        "action": action,
        "jti": secrets.token_hex(10),
        "token_type": "action",
        "iat": now,
        "exp": now + expires_seconds,
    }
    return encode_jwt(payload)


def hash_token_identifier(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


# -------------------------------------------------------------------------
# SECRET ENCRYPTION (FOR BROKER TOKENS / SENSITIVE CREDENTIALS AT REST)
# -------------------------------------------------------------------------
def encrypt_secret(plaintext: str) -> str:
    """Authenticated stream cipher with HMAC-SHA256 key derivation + integrity tag."""
    if not plaintext:
        return ""
    nonce = os.urandom(16)
    master = settings.SECRET_ENCRYPTION_KEY.encode("utf-8")
    data = plaintext.encode("utf-8")

    # Derive keystream blocks via SHA-256 counter mode
    keystream = bytearray()
    counter = 0
    while len(keystream) < len(data):
        block = hashlib.sha256(master + nonce + counter.to_bytes(4, "big")).digest()
        keystream.extend(block)
        counter += 1

    ciphertext = bytes(b ^ k for b, k in zip(data, keystream[:len(data)]))
    mac = hmac.new(master, nonce + ciphertext, hashlib.sha256).digest()
    return f"enc1${_b64url_encode(nonce)}${_b64url_encode(ciphertext)}${_b64url_encode(mac)}"


def decrypt_secret(token: str) -> str:
    if not token or not token.startswith("enc1$"):
        return token
    try:
        _, nonce_b64, ct_b64, mac_b64 = token.split("$")
        nonce = _b64url_decode(nonce_b64)
        ciphertext = _b64url_decode(ct_b64)
        provided_mac = _b64url_decode(mac_b64)
        master = settings.SECRET_ENCRYPTION_KEY.encode("utf-8")
        expected_mac = hmac.new(master, nonce + ciphertext, hashlib.sha256).digest()
        if not hmac.compare_digest(provided_mac, expected_mac):
            raise ValueError("Secret integrity check failed")

        keystream = bytearray()
        counter = 0
        while len(keystream) < len(ciphertext):
            block = hashlib.sha256(master + nonce + counter.to_bytes(4, "big")).digest()
            keystream.extend(block)
            counter += 1

        plaintext = bytes(b ^ k for b, k in zip(ciphertext, keystream[:len(ciphertext)]))
        return plaintext.decode("utf-8")
    except Exception:
        return ""


# -------------------------------------------------------------------------
# SLIDING WINDOW IN-MEMORY RATE LIMITER
# -------------------------------------------------------------------------
class RateLimiter:
    def __init__(self):
        self._lock = threading.Lock()
        self._hits: Dict[str, deque] = defaultdict(deque)

    def check(self, key: str, max_requests: int, window_seconds: int = 60) -> Tuple[bool, int]:
        """Returns (allowed, retry_after_seconds)."""
        now = time.time()
        cutoff = now - window_seconds
        with self._lock:
            q = self._hits[key]
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= max_requests:
                retry_after = max(1, int(q[0] + window_seconds - now))
                return False, retry_after
            q.append(now)
            return True, 0


auth_rate_limiter = RateLimiter()
