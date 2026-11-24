import unittest
import json
from unittest.mock import patch, MagicMock
from brokers import (
    BaseBrokerClient,
    ZerodhaKiteClient,
    AngelSmartApiClient,
    DhanHqClient,
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


if __name__ == "__main__":
    unittest.main()
