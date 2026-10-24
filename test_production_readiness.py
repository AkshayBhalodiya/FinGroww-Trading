"""
FinGroww Production Readiness Test Suite
Verifies all 8 Pillars:
- Market Proxy Health
- Live Quote & Candle Integrity
- Option Chain & Real PCR
- MongoDB / Resilient Datastore API Operations
- Signal Recording & Evaluation Engine
- Authentication Endpoints
- Risk/Reward & Quantitative Calculation Engine
"""
import unittest
import requests
import time

BASE_URL = "http://127.0.0.1:8787"

class TestFinGrowwProductionReadiness(unittest.TestCase):

    def test_01_server_health(self):
        """Pillar 8: Test server health endpoint."""
        r = requests.get(f"{BASE_URL}/api/health", timeout=5)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data.get("ok"))
        self.assertIn("source", data)

    def test_02_system_status(self):
        """Pillar 2 & 8: Test system diagnostic and database status."""
        r = requests.get(f"{BASE_URL}/api/system/status", timeout=5)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("database", data)
        self.assertIn("market_proxy", data)
        self.assertEqual(data.get("market_proxy", {}).get("yahoo_bridge"), "Operational")

    def test_03_live_market_data(self):
        """Pillar 1 & 3: Test live OHLCV feed and spot price integrity."""
        r = requests.get(f"{BASE_URL}/api/live?symbol=NIFTY%2050&interval=15m", timeout=15)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertGreater(data.get("lastPrice", 0), 1000)
        series = data.get("series", [])
        self.assertGreaterEqual(len(series), 30)
        # Verify OHLC structure
        first_bar = series[0]
        for key in ("o", "h", "l", "c", "t"):
            self.assertIn(key, first_bar)

    def test_04_option_chain_pcr(self):
        """Pillar 6: Test genuine option chain strikes and PCR calculation."""
        r = requests.get(f"{BASE_URL}/api/option-chain?symbol=NIFTY%2050", timeout=15)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertGreater(data.get("spotPrice", 0), 1000)
        self.assertGreater(data.get("atmStrike", 0), 1000)
        self.assertGreater(data.get("pcr", 0), 0)
        chain = data.get("chain", [])
        self.assertGreaterEqual(len(chain), 10)
        # Check strike row integrity
        atm_row = chain[0]
        self.assertIn("CE", atm_row)
        self.assertIn("PE", atm_row)
        self.assertIn("ltp", atm_row["CE"])

    def test_05_signal_recording_and_retrieval(self):
        """Pillar 2 & 4: Test signal generation recording and retrieval."""
        test_signal = {
            "symbol": "NIFTY 50",
            "timeframe": "15m",
            "signal": "BUY",
            "entry": 22600.0,
            "sl": 22450.0,
            "tp": 22750.0,
            "score": 85.0,
            "indicators": {"rsi": 54.2, "supertrend": 1}
        }
        post_r = requests.post(f"{BASE_URL}/api/signals", json=test_signal, timeout=5)
        self.assertEqual(post_r.status_code, 201)
        saved = post_r.json().get("signal", {})
        self.assertEqual(saved.get("signal_type"), "BUY")
        self.assertIn("signal_id", saved)

        # Retrieve saved signals
        get_r = requests.get(f"{BASE_URL}/api/signals?symbol=NIFTY%2050&limit=5", timeout=5)
        self.assertEqual(get_r.status_code, 200)
        signals = get_r.json().get("signals", [])
        self.assertGreaterEqual(len(signals), 1)

    def test_06_trade_outcomes_evaluator(self):
        """Pillar 2 & 5: Test automated trade outcome evaluation."""
        r = requests.get(f"{BASE_URL}/api/trade-outcomes", timeout=5)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("win_rate_percent", data)
        self.assertIn("profit_factor", data)

    def test_07_user_authentication(self):
        """Pillar 2: Test secure registration and login."""
        unique_email = f"trader_{int(time.time())}@fingroww.test"
        reg_payload = {
            "email": unique_email,
            "password": "StrongPassword123!",
            "name": "Quant Trader"
        }
        reg_r = requests.post(f"{BASE_URL}/api/auth/register", json=reg_payload, timeout=5)
        self.assertEqual(reg_r.status_code, 201)
        token = reg_r.json().get("token")
        self.assertTrue(token)

        # Test login
        login_r = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": unique_email,
            "password": "StrongPassword123!"
        }, timeout=5)
        self.assertEqual(login_r.status_code, 200)

        # Test auth/me with bearer token
        me_r = requests.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": f"Bearer {token}"}, timeout=5)
        self.assertEqual(me_r.status_code, 200)
        self.assertEqual(me_r.json().get("user", {}).get("email"), unique_email)

if __name__ == "__main__":
    unittest.main()

