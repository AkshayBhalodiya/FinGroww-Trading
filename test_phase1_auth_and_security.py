#!/usr/bin/env python3
"""
FinGroww SaaS Modernisation (Phase 1) — Auth, Security, JWT & Isolation Test Suite.
Tests Password Hashing, JWT Lifecycle, Session Revocation, RBAC, User Isolation,
Database 24-Collection Schema, and FastAPI/Flask API parity.
"""

import hashlib
import os
import tempfile
import time
import unittest
import uuid

from backend.database import COLLECTION_NAMES, DatabaseManager, db_manager
from backend.security import (
    create_access_token,
    create_refresh_token,
    decode_jwt,
    decrypt_secret,
    encode_jwt,
    encrypt_secret,
    has_permission,
    hash_password,
    verify_password,
)
from backend.services import auth_service
import fingroww_market_server as srv


class TestPhase1SecurityPrimitives(unittest.TestCase):
    def test_01_scrypt_salted_hashing_and_legacy_migration(self):
        pw = "FinGroww@2026"
        h1 = hash_password(pw)
        h2 = hash_password(pw)
        self.assertTrue(h1.startswith("scrypt$16384$8$1$"))
        self.assertNotEqual(h1, h2)  # Per-user random salt

        ok, needs_rehash = verify_password(pw, h1)
        self.assertTrue(ok)
        self.assertFalse(needs_rehash)

        bad, _ = verify_password("WrongPass123", h1)
        self.assertFalse(bad)

        # Legacy SHA-256 verification flags needs_rehash=True
        legacy = hashlib.sha256(pw.encode("utf-8")).hexdigest()
        ok_legacy, rehash_flag = verify_password(pw, legacy)
        self.assertTrue(ok_legacy)
        self.assertTrue(rehash_flag)

    def test_02_jwt_signing_tampering_and_expiry(self):
        access = create_access_token("USR-1", "a@b.com", "trader", "SES-1", "trader_a")
        decoded = decode_jwt(access, expected_type="access")
        self.assertIsNotNone(decoded)
        self.assertEqual(decoded["sub"], "USR-1")

        # Refresh check rejects access token
        self.assertIsNone(decode_jwt(access, expected_type="refresh"))

        # Tampered payload fails signature check
        parts = access.split(".")
        tampered = f"{parts[0]}.{parts[1][:-2]}aa.{parts[2]}"
        self.assertIsNone(decode_jwt(tampered))

        # Expired token fails check
        expired = encode_jwt({"sub": "USR-1", "token_type": "access", "exp": time.time() - 5})
        self.assertIsNone(decode_jwt(expired, expected_type="access"))

    def test_03_secret_encryption_roundtrip_and_integrity(self):
        api_secret = "kite_live_secret_xyz_998877"
        enc = encrypt_secret(api_secret)
        self.assertTrue(enc.startswith("enc1$"))
        self.assertNotIn(api_secret, enc)
        self.assertEqual(decrypt_secret(enc), api_secret)

        # Tampering ciphertext returns empty
        bad = enc[:-2] + ("A" if enc[-2:] != "AA" else "B")
        self.assertEqual(decrypt_secret(bad), "")

    def test_04_rbac_matrix_enforcement(self):
        self.assertTrue(has_permission("super_admin", "users:delete"))
        self.assertTrue(has_permission("super_admin", "admin:anything"))
        self.assertTrue(has_permission("admin", "users:suspend"))
        self.assertFalse(has_permission("trader", "users:suspend"))
        self.assertFalse(has_permission("trader", "admin:*"))
        self.assertTrue(has_permission("pro_trader", "broker:live_execute"))
        self.assertFalse(has_permission("trader", "broker:live_execute"))


class TestPhase1AuthEndpointsAndIsolation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp_dir = tempfile.TemporaryDirectory()
        cls._store_file = os.path.join(cls._tmp_dir.name, "test_v2_store.json")
        # Redirect global db_manager to isolated test datastore
        db_manager._initialized = False
        db_manager._local_path = cls._store_file
        db_manager._local_store = {name: [] for name in COLLECTION_NAMES}
        db_manager._local_collections = {}
        db_manager.init(force_local=True)

        srv.app.testing = True
        cls.client = srv.app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls._tmp_dir.cleanup()

    def test_05_all_24_collections_initialized(self):
        self.assertGreaterEqual(len(COLLECTION_NAMES), 24)
        for req in ["users", "sessions", "login_history", "paper_accounts", "trading_journals", "audit_logs", "plans"]:
            self.assertIn(req, COLLECTION_NAMES)
        self.assertGreaterEqual(db_manager.collection("plans").count_documents({}), 2)

    def test_06_v2_register_verify_login_profile_lifecycle(self):
        email = f"phase1_{uuid.uuid4().hex[:6]}@fingroww.tech"
        # Reject weak password (<8 or missing digit)
        r_weak = self.client.post("/api/v2/auth/register", json={
            "email": email,
            "password": "passwordonly",
            "full_name": "Weak Pw",
        })
        self.assertEqual(r_weak.status_code, 422)

        # Valid registration
        r_reg = self.client.post("/api/v2/auth/register", json={
            "email": email,
            "password": "StrongPass123",
            "full_name": "Akshay Tester",
            "experience_level": "pro_algo",
        })
        self.assertEqual(r_reg.status_code, 201)
        data = r_reg.get_json()
        self.assertTrue(data["ok"])
        self.assertIn("access_token", data)
        self.assertIn("refresh_token", data)
        user_id = data["user"]["user_id"]
        otp = data.get("verification_otp_dev")
        self.assertIsNotNone(otp)

        # Check auto-provisioned isolated paper account & preferences
        acc = db_manager.collection("paper_accounts").find_one({"user_id": user_id})
        self.assertIsNotNone(acc)
        self.assertEqual(acc["virtual_capital"], 100000.0)

        # Duplicate email fails with 409
        r_dup = self.client.post("/api/v2/auth/register", json={
            "email": email,
            "password": "StrongPass123",
            "full_name": "Dup User",
        })
        self.assertEqual(r_dup.status_code, 409)

        # Verify email with OTP
        r_ver = self.client.post("/api/v2/auth/verify-email", json={
            "email": email,
            "otp_or_token": otp,
        })
        self.assertEqual(r_ver.status_code, 200)

        # Profile GET & PUT
        headers = {"Authorization": f"Bearer {data['access_token']}"}
        r_me = self.client.get("/api/v2/users/me", headers=headers)
        self.assertEqual(r_me.status_code, 200)
        self.assertTrue(r_me.get_json()["user"]["is_email_verified"])

        r_upd = self.client.put("/api/v2/users/me", headers=headers, json={
            "trading_style": "scalper",
            "risk_profile": "conservative",
        })
        self.assertEqual(r_upd.status_code, 200)
        self.assertEqual(r_upd.get_json()["user"]["trading_style"], "scalper")

        # Active sessions & Login history
        r_ses = self.client.get("/api/v2/users/me/sessions", headers=headers)
        self.assertEqual(r_ses.status_code, 200)
        self.assertGreaterEqual(r_ses.get_json()["count"], 1)

        r_hist = self.client.get("/api/v2/users/me/login-history", headers=headers)
        self.assertEqual(r_hist.status_code, 200)
        self.assertGreaterEqual(r_hist.get_json()["count"], 1)

    def test_07_refresh_rotation_and_logout_revocation(self):
        email = f"rot_{uuid.uuid4().hex[:6]}@fingroww.tech"
        r = self.client.post("/api/v2/auth/register", json={
            "email": email,
            "password": "RotatePass99",
            "full_name": "Rotation User",
        })
        d = r.get_json()
        access1 = d["access_token"]
        refresh1 = d["refresh_token"]

        # Refresh issues new pair
        r_ref = self.client.post("/api/v2/auth/refresh", json={"refresh_token": refresh1})
        self.assertEqual(r_ref.status_code, 200)
        d2 = r_ref.get_json()
        access2 = d2["access_token"]
        refresh2 = d2["refresh_token"]
        self.assertNotEqual(refresh1, refresh2)

        # Logout revokes session
        r_out = self.client.post("/api/v2/auth/logout", headers={"Authorization": f"Bearer {access2}"})
        self.assertEqual(r_out.status_code, 200)

        # Subsequent call with revoked access token returns 401
        r_me_fail = self.client.get("/api/v2/users/me", headers={"Authorization": f"Bearer {access2}"})
        self.assertEqual(r_me_fail.status_code, 401)

    def test_08_forgot_and_reset_password_invalidates_sessions(self):
        email = f"rst_{uuid.uuid4().hex[:6]}@fingroww.tech"
        r = self.client.post("/api/v2/auth/register", json={
            "email": email,
            "password": "OldPassword1",
            "full_name": "Reset Tester",
        })
        old_access = r.get_json()["access_token"]

        r_forgot = self.client.post("/api/v2/auth/forgot-password", json={"email": email})
        self.assertEqual(r_forgot.status_code, 200)
        reset_tok = r_forgot.get_json()["reset_token_dev"]

        r_reset = self.client.post("/api/v2/auth/reset-password", json={
            "token": reset_tok,
            "new_password": "NewPassword99",
        })
        self.assertEqual(r_reset.status_code, 200)

        # Old access token is now rejected
        self.assertEqual(
            self.client.get("/api/v2/users/me", headers={"Authorization": f"Bearer {old_access}"}).status_code,
            401,
        )

        # Old password fails login, new password succeeds
        self.assertEqual(
            self.client.post("/api/v2/auth/login", json={"email": email, "password": "OldPassword1"}).status_code,
            401,
        )
        self.assertEqual(
            self.client.post("/api/v2/auth/login", json={"email": email, "password": "NewPassword99"}).status_code,
            200,
        )

    def test_09_cross_user_paper_isolation_when_authenticated(self):
        # Register User A and User B
        r_a = self.client.post("/api/v2/auth/register", json={
            "email": f"usera_{uuid.uuid4().hex[:5]}@fingroww.tech",
            "password": "PasswordA123",
            "full_name": "User Alpha",
            "username": f"alpha_{uuid.uuid4().hex[:5]}",
        }).get_json()
        r_b = self.client.post("/api/v2/auth/register", json={
            "email": f"userb_{uuid.uuid4().hex[:5]}@fingroww.tech",
            "password": "PasswordB123",
            "full_name": "User Beta",
            "username": f"beta_{uuid.uuid4().hex[:5]}",
        }).get_json()

        uname_a = r_a["user"]["trading_profile_name"]
        uname_b = r_b["user"]["trading_profile_name"]

        # Attacker B tries to access User A's paper session via ?user=uname_a with B's JWT
        res = self.client.get(
            f"/api/paper/session/state?user={uname_a}",
            headers={"Authorization": f"Bearer {r_b['access_token']}"},
        )
        self.assertEqual(res.status_code, 200)
        state = res.get_json()
        # Server MUST return B's own isolated session, NEVER A's!
        self.assertEqual(state["user_name"], uname_b)
        self.assertNotEqual(state["user_name"], uname_a)

    def test_10_legacy_sha256_password_auto_upgrades_on_login(self):
        email = f"leg_{uuid.uuid4().hex[:6]}@fingroww.tech"
        pw = "LegacyPass123"
        user_id = f"USR-{uuid.uuid4().hex[:8].upper()}"
        db_manager.collection("users").insert_one({
            "user_id": user_id,
            "email": email,
            "username": f"leg_{uuid.uuid4().hex[:4]}",
            "full_name": "Legacy User",
            "password_hash": hashlib.sha256(pw.encode("utf-8")).hexdigest(),
            "role": "trader",
            "account_status": "active",
            "is_email_verified": True,
        })

        r_login = self.client.post("/api/v2/auth/login", json={"email": email, "password": pw})
        self.assertEqual(r_login.status_code, 200)

        # Verify stored hash in DB was automatically upgraded to salted scrypt!
        updated_user = db_manager.collection("users").find_one({"user_id": user_id})
        self.assertTrue(updated_user["password_hash"].startswith("scrypt$"))

    def test_11_fastapi_app_openapi_and_routes_loaded(self):
        from backend.app import app as fastapi_app
        openapi_paths = set(fastapi_app.openapi().get("paths", {}).keys())
        self.assertIn("/api/v2/auth/register", openapi_paths)
        self.assertIn("/api/v2/auth/login", openapi_paths)
        self.assertIn("/api/v2/users/me", openapi_paths)
        self.assertIn("/api/v2/health", openapi_paths)


if __name__ == "__main__":
    unittest.main(verbosity=2)
