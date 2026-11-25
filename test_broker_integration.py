import unittest
import json
from unittest.mock import patch, MagicMock
from brokers import (
    BaseBrokerClient,
    ZerodhaKiteClient,
    AngelSmartApiClient,
    DhanHqClient,
    UpstoxClient,
    broker_manager,
)
from fingroww_market_server import app


class TestBrokerIntegration(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.user = "UnitTest_BrokerTrader"
        broker_manager.disconnect_broker(self.user)

    def test_01_broker_manager_initial_state(self):
        """Verifies broker manager returns disconnected paper mode by default."""
        status = broker_manager.get_status(self.user)
        self.assertFalse(status["is_connected"])
        self.assertEqual(status["mode"], "PAPER")
        self.assertIsNone(status["broker_name"])

        # Cannot switch to REAL mode without connected broker
        ok, msg = broker_manager.set_trading_mode(self.user, "REAL")
        self.assertFalse(ok)
        self.assertIn("without an active connected broker", msg.lower())

    def test_02_zerodha_kite_client_flow(self):
        """Tests Zerodha Kite Connect client with mocked network calls."""
        kite = ZerodhaKiteClient()

        # Missing credentials validation
        ok, err, _ = kite.authenticate({"api_key": ""})
        self.assertFalse(ok)
        self.assertIn("required", err.lower())

        # Mocked successful Kite authentication
        with patch("requests.get") as mock_get, patch("requests.post") as mock_post:
            # 1. Profile response
            mock_profile_res = MagicMock()
            mock_profile_res.status_code = 200
            mock_profile_res.json.return_value = {
                "status": "success",
                "data": {"user_id": "AB1234", "user_name": "Akshay Bhalodiya"}
            }
            mock_get.return_value = mock_profile_res

            ok, msg, profile = kite.authenticate({"api_key": "kite_key", "access_token": "kite_tok", "client_id": "AB1234"})
            self.assertTrue(ok)
            self.assertTrue(kite.is_connected)
            self.assertEqual(kite.client_id, "AB1234")

            # 2. Get Funds
            mock_margins_res = MagicMock()
            mock_margins_res.status_code = 200
            mock_margins_res.json.return_value = {
                "status": "success",
                "data": {
                    "equity": {
                        "available": {"live_balance": 150000.0, "collateral": 25000.0},
                        "utilised": {"debits": 35000.0},
                        "net": 185000.0
                    }
                }
            }
            mock_get.return_value = mock_margins_res
            ok_f, funds, _ = kite.get_funds()
            self.assertTrue(ok_f)
            self.assertEqual(funds["available_cash"], 150000.0)
            self.assertEqual(funds["used_margin"], 35000.0)

            # 3. Place Order
            mock_order_res = MagicMock()
            mock_order_res.status_code = 200
            mock_order_res.json.return_value = {
                "status": "success",
                "data": {"order_id": "2411240001"}
            }
            mock_post.return_value = mock_order_res
            ok_o, o_data, _ = kite.place_order(
                symbol="NIFTY 24500 CE",
                quantity=65,
                side="BUY",
                order_type="MARKET",
                stop_loss=200.0
            )
            self.assertTrue(ok_o)
            self.assertEqual(o_data["order_id"], "2411240001")

    def test_03_angel_one_smartapi_client_flow(self):
        """Tests Angel One SmartAPI client with mocked network responses."""
        angel = AngelSmartApiClient()

        # Missing credentials validation
        ok, err, _ = angel.authenticate({"api_key": ""})
        self.assertFalse(ok)
        self.assertIn("required", err.lower())

        with patch("requests.get") as mock_get, patch("requests.post") as mock_post:
            # Mock JWT direct auth
            ok, msg, _ = angel.authenticate({"api_key": "smart_key", "client_id": "ANG123", "jwt_token": "mock_jwt"})
            self.assertTrue(ok)
            self.assertTrue(angel.is_connected)

            # Get RMS funds
            mock_rms = MagicMock()
            mock_rms.status_code = 200
            mock_rms.json.return_value = {
                "status": True,
                "data": {"net": 200000.0, "availablecash": 180000.0, "utilisedamount": 20000.0}
            }
            mock_get.return_value = mock_rms
            ok_f, funds, _ = angel.get_funds()
            self.assertTrue(ok_f)
            self.assertEqual(funds["available_cash"], 180000.0)

    def test_04_dhan_hq_client_flow(self):
        """Tests DhanHQ API client with mocked network calls."""
        dhan = DhanHqClient()

        # Missing credentials validation
        ok, err, _ = dhan.authenticate({"access_token": ""})
        self.assertFalse(ok)
        self.assertIn("required", err.lower())

        with patch("requests.get") as mock_get:
            mock_res = MagicMock()
            mock_res.status_code = 200
            mock_res.json.return_value = {
                "availabelBalance": 95000.0,
                "utilizedAmount": 15000.0,
                "sodLimit": 110000.0
            }
            mock_get.return_value = mock_res
            ok, _, _ = dhan.authenticate({"client_id": "1000012345", "access_token": "mock_dhan_token"})
            self.assertTrue(ok)
            self.assertTrue(dhan.is_connected)

            ok_f, funds, _ = dhan.get_funds()
            self.assertTrue(ok_f)
            self.assertEqual(funds["available_cash"], 95000.0)

    def test_05_broker_routes_api_endpoints(self):
        """Tests Flask broker REST API routes."""
        # 1. Status
        res = self.client.get(f"/api/broker/status?user={self.user}")
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data["ok"])
        self.assertEqual(data["status"]["mode"], "PAPER")

        # 2. Rejection on place real order without broker connected
        res_order = self.client.post(
            f"/api/broker/order/place?user={self.user}",
            json={"symbol": "NIFTY 24500 CE", "quantity": 65, "side": "BUY", "stop_loss": 200.0}
        )
        self.assertEqual(res_order.status_code, 400)
        self.assertIn("no active broker", json.loads(res_order.data).get("error", "").lower())

        # 3. Disconnect
        res_disc = self.client.post(f"/api/broker/disconnect?user={self.user}")
        self.assertEqual(res_disc.status_code, 200)

    def test_06_upstox_client_flow(self):
        """Tests Upstox API v2 client with mocked network calls."""
        upstox = UpstoxClient()

        # Missing token validation
        ok, err, _ = upstox.authenticate({"access_token": ""})
        self.assertFalse(ok)
        self.assertIn("required", err.lower())

        with patch("requests.get") as mock_get, patch("requests.post") as mock_post:
            # 1. Profile response
            mock_profile = MagicMock()
            mock_profile.status_code = 200
            mock_profile.json.return_value = {
                "status": "success",
                "data": {"user_id": "UP12345", "user_name": "Akshay Upstox"}
            }
            mock_get.return_value = mock_profile

            ok, msg, profile = upstox.authenticate({"access_token": "mock_upstox_jwt", "client_id": "UP12345"})
            self.assertTrue(ok)
            self.assertTrue(upstox.is_connected)
            self.assertEqual(upstox.client_id, "UP12345")

            # 2. Funds
            mock_funds = MagicMock()
            mock_funds.status_code = 200
            mock_funds.json.return_value = {
                "status": "success",
                "data": {
                    "equity": {
                        "available_margin": 140000.0,
                        "used_margin": 25000.0,
                        "payin_amount": 5000.0
                    }
                }
            }
            mock_get.return_value = mock_funds
            ok_f, funds, _ = upstox.get_funds()
            self.assertTrue(ok_f)
            self.assertEqual(funds["available_cash"], 140000.0)
            self.assertEqual(funds["used_margin"], 25000.0)
            self.assertEqual(funds["broker"], "UPSTOX")

            # 3. Place Order
            mock_order = MagicMock()
            mock_order.status_code = 200
            mock_order.json.return_value = {
                "status": "success",
                "data": {"order_id": "UPSTOX_ORD_9999"}
            }
            mock_post.return_value = mock_order
            ok_o, o_data, _ = upstox.place_order(
                symbol="NIFTY 24500 CE",
                quantity=65,
                side="BUY",
                order_type="MARKET",
                stop_loss=210.0
            )
            self.assertTrue(ok_o)
            self.assertEqual(o_data["order_id"], "UPSTOX_ORD_9999")
            self.assertEqual(o_data["broker"], "UPSTOX")

            # 4. Connect via BrokerManager
            mock_get.return_value = mock_profile
            ok_m, msg_m, prof_m = broker_manager.connect_broker(
                self.user,
                "UPSTOX",
                {"access_token": "mock_upstox_jwt", "client_id": "UP12345"}
            )
            self.assertTrue(ok_m)
            self.assertEqual(prof_m["broker"], "UPSTOX")

            # Verify mode toggle to REAL succeeds with Upstox
            ok_mode, _ = broker_manager.set_trading_mode(self.user, "REAL")
            self.assertTrue(ok_mode)
            self.assertEqual(broker_manager.get_trading_mode(self.user), "REAL")

            # Cleanup
            broker_manager.disconnect_broker(self.user)
            self.assertEqual(broker_manager.get_trading_mode(self.user), "PAPER")

    def test_07_multi_user_broker_isolation(self):
        """Verifies complete multi-user isolation across broker connections, funds, and modes."""
        u1 = "UnitTest_User_Akshay"
        u2 = "UnitTest_User_Vijay"
        u3 = "UnitTest_User_Rahul"
        u4 = "UnitTest_User_Pooja"

        # Disconnect all first
        for u in (u1, u2, u3, u4):
            broker_manager.disconnect_broker(u)

        with patch("requests.get") as mock_get:
            # 1. Connect User 1 to Zerodha
            mock_res_kite = MagicMock()
            mock_res_kite.status_code = 200
            mock_res_kite.json.return_value = {
                "status": "success",
                "data": {"user_id": "KITE_AKSHAY", "user_name": "Akshay Kite"}
            }
            mock_get.return_value = mock_res_kite
            ok1, _, _ = broker_manager.connect_broker(u1, "ZERODHA_KITE", {"api_key": "k", "access_token": "tok"})
            self.assertTrue(ok1)
            broker_manager.set_trading_mode(u1, "REAL")

            # 2. Connect User 2 to Dhan
            mock_res_dhan = MagicMock()
            mock_res_dhan.status_code = 200
            mock_res_dhan.json.return_value = {"availabelBalance": 50000.0, "sodLimit": 50000.0}
            mock_get.return_value = mock_res_dhan
            ok2, _, _ = broker_manager.connect_broker(u2, "DHAN", {"client_id": "DHAN_VIJAY", "access_token": "tok"})
            self.assertTrue(ok2)
            broker_manager.set_trading_mode(u2, "REAL")

            # 3. Connect User 3 to Upstox
            mock_res_upstox = MagicMock()
            mock_res_upstox.status_code = 200
            mock_res_upstox.json.return_value = {
                "status": "success",
                "data": {"user_id": "UPSTOX_RAHUL", "user_name": "Rahul Upstox"}
            }
            mock_get.return_value = mock_res_upstox
            ok3, _, _ = broker_manager.connect_broker(u3, "UPSTOX", {"access_token": "tok", "client_id": "UPSTOX_RAHUL"})
            self.assertTrue(ok3)

            # User 4 connects nothing

            # 4. Assert strict isolation via Flask REST API
            r1 = self.client.get(f"/api/broker/status?user={u1}").get_json()
            self.assertTrue(r1["connected"])
            self.assertEqual(r1["broker"], "ZERODHA_KITE")
            self.assertEqual(r1["mode"], "REAL")

            r2 = self.client.get(f"/api/broker/status?user={u2}").get_json()
            self.assertTrue(r2["connected"])
            self.assertEqual(r2["broker"], "DHAN")
            self.assertEqual(r2["mode"], "REAL")

            r3 = self.client.get(f"/api/broker/status?user={u3}").get_json()
            self.assertTrue(r3["connected"])
            self.assertEqual(r3["broker"], "UPSTOX")
            self.assertEqual(r3["mode"], "PAPER")

            r4 = self.client.get(f"/api/broker/status?user={u4}").get_json()
            self.assertFalse(r4["connected"])
            self.assertIsNone(r4["broker"])
            self.assertEqual(r4["mode"], "PAPER")

            # 5. Disconnect User 1 and ensure Users 2 & 3 remain connected
            broker_manager.disconnect_broker(u1)
            self.assertFalse(broker_manager.get_status(u1)["is_connected"])
            self.assertTrue(broker_manager.get_status(u2)["is_connected"])
            self.assertTrue(broker_manager.get_status(u3)["is_connected"])

        # Final cleanup
        for u in (u1, u2, u3, u4):
            broker_manager.disconnect_broker(u)

    def test_09_indian_multi_broker_ecosystem(self):
        """Verifies all 10 additional Indian brokers can authenticate, check funds, and route orders."""
        brokers_to_test = [
            ("GROWW", {"client_id": "GW123", "access_token": "gw_tok"}),
            ("KOTAK_NEO", {"consumer_key": "kn_key", "access_token": "kn_tok"}),
            ("FYERS", {"app_id": "FY123-100", "access_token": "fy_tok"}),
            ("SHOONYA", {"user_id": "SH123", "password": "sh_password", "api_key": "sh_key"}),
            ("ICICI_DIRECT", {"api_key": "icici_key", "session_token": "icici_tok"}),
            ("HDFC_SKY", {"api_key": "hdfc_key", "access_token": "hdfc_tok"}),
            ("PAYTM_MONEY", {"api_key": "pm_key", "request_token": "pm_tok"}),
            ("FIVE_PAISA", {"user_id": "5P123", "user_key": "5p_key"}),
            ("ALICE_BLUE", {"user_id": "AB123", "api_key": "ab_key"}),
            ("MOTILAL_OSWAL", {"client_code": "MO123", "api_key": "mo_key"}),
        ]

        test_user = "IndianBrokerTester"
        for broker_key, creds in brokers_to_test:
            broker_manager.disconnect_broker(test_user)

            # 1. Connect via broker_manager
            ok, msg, profile = broker_manager.connect_broker(test_user, broker_key, creds)
            self.assertTrue(ok, f"Failed to connect {broker_key}: {msg}")
            status = broker_manager.get_status(test_user)
            self.assertTrue(status["is_connected"])
            self.assertEqual(status["broker_name"], broker_key)

            # 2. Get funds
            client = broker_manager.get_client(test_user)
            self.assertIsNotNone(client)
            ok_f, funds, _ = client.get_funds()
            self.assertTrue(ok_f)
            self.assertGreater(funds["available_cash"], 0)

            # 3. Place real order
            ok_o, order_doc, _ = client.place_order(
                symbol="NIFTY 24500 CE",
                quantity=65,
                side="BUY",
                order_type="MARKET",
                price=150.0,
                stop_loss=120.0
            )
            self.assertTrue(ok_o)
            self.assertEqual(order_doc["status"], "COMPLETE")

            # 4. REST endpoint test
            res = self.client.get(f"/api/broker/status?user={test_user}").get_json()
            self.assertTrue(res["connected"])
            self.assertEqual(res["broker"], broker_key)

        broker_manager.disconnect_broker(test_user)


if __name__ == "__main__":
    unittest.main()
