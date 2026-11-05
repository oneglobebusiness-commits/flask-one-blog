import logging

import bcrypt
from flask import current_app

from ..core import db, utcnow

log = logging.getLogger(__name__)
DEFAULT_ADMIN_PASSWORD = "Admin@123"


def hash_password(password):
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt(10)).decode()


def check_password(password, hashed):
    if not hashed:
        return False
    return bcrypt.checkpw(password.encode()[:72], hashed.encode())


def run_seeds():
    now = utcnow()
    db().plans.update_one(
        {"name": "Free"},
        {
            "$setOnInsert": {
                "price": 0,
                "ForDays": 1,
                "articalsNumber": 1,
                "maxTopics": 1,
                "maxStores": 1,
                "analyticsEnabled": False,
                "scheduleEnabled": False,
                "isActive": True,
                "createdAt": now,
                "updatedAt": now,
            }
        },
        upsert=True,
    )

    email = current_app.config["ADMIN_EMAIL"]
    password = current_app.config["ADMIN_PASSWORD"]
    admin = db().users.find_one({"role": "admin"})
    if admin and password and check_password(DEFAULT_ADMIN_PASSWORD, admin.get("password")):
        # Replace the password the old app hardcoded.
        db().users.update_one(
            {"_id": admin["_id"]},
            {"$set": {"password": hash_password(password), "updatedAt": now}},
        )
        log.warning("The old default admin password was replaced with ADMIN_PASSWORD.")
    elif not admin and email and password:
        db().users.insert_one(
            {
                "email": email,
                "password": hash_password(password),
                "role": "admin",
                "isActive": True,
                "createdAt": now,
                "updatedAt": now,
            }
        )
