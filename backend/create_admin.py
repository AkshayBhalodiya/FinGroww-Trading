"""
FinGroww SaaS Platform — Super Admin Bootstrap CLI.
Creates or promotes a Super Admin account cleanly without hardcoding secrets in application code.

Usage:
  python -m backend.create_admin --email admin@fingroww.tech --password YourStrongPassword123 --name "Akshay"
"""

import argparse
import sys

from backend.database import db_manager
from backend.security import hash_password
from backend.services import auth_service


def bootstrap_super_admin(email: str, password: str, full_name: str = "Akshay (Super Admin)") -> dict:
    db_manager.init()
    email_norm = email.strip().lower()
    users_col = db_manager.collection("users")
    existing = users_col.find_one({"email": email_norm})

    if existing:
        users_col.update_one(
            {"user_id": existing["user_id"]},
            {
                "$set": {
                    "role": "super_admin",
                    "subscription_plan": "pro_algo_swarm",
                    "account_status": "active",
                    "is_email_verified": True,
                    "password_hash": hash_password(password),
                }
            },
        )
        return users_col.find_one({"user_id": existing["user_id"]}, {"_id": 0, "password_hash": 0})

    res = auth_service.register_user(
        email=email_norm,
        password=password,
        full_name=full_name,
        username="superadmin",
        experience_level="pro_algo",
        trading_style="intraday_momentum",
        role="super_admin",
    )
    uid = res["user"]["user_id"]
    users_col.update_one(
        {"user_id": uid},
        {"$set": {"is_email_verified": True, "subscription_plan": "pro_algo_swarm"}},
    )
    return users_col.find_one({"user_id": uid}, {"_id": 0, "password_hash": 0})


def main():
    parser = argparse.ArgumentParser(description="Create or promote a FinGroww Super Admin user.")
    parser.add_argument("--email", required=True, help="Admin email address")
    parser.add_argument("--password", required=True, help="Admin password (min 8 chars, letters + numbers)")
    parser.add_argument("--name", default="Akshay (Super Admin)", help="Full name")
    args = parser.parse_args()

    if len(args.password) < 8 or not any(c.isalpha() for c in args.password) or not any(c.isdigit() for c in args.password):
        print("Error: Password must be at least 8 characters and include letters and numbers.", file=sys.stderr)
        sys.exit(1)

    user = bootstrap_super_admin(args.email, args.password, args.name)
    print(f"Super Admin ready: {user['email']} (user_id={user['user_id']}, role={user['role']})")


if __name__ == "__main__":
    main()
