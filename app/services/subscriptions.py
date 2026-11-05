import math
from datetime import timedelta

from ..core import ApiError, as_utc, db, oid, utcnow

ACTIVE, EXPIRED, CANCELLED = "active", "expired", "cancelled"
FEATURES = ("articles", "topics")


def create(user_id, plan_id):
    user_oid, plan_oid = oid(user_id, "User"), oid(plan_id, "Plan")
    if not db().users.find_one({"_id": user_oid}):
        raise ApiError(404, "User not found.")
    plan = db().plans.find_one({"_id": plan_oid})
    if not plan:
        raise ApiError(404, "Plan not found.")
    if not plan.get("isActive"):
        raise ApiError(400, "Selected plan is inactive.")
    if active(user_id):
        raise ApiError(400, "User already has an active subscription.")
    return _insert(user_oid, plan)


def _insert(user_oid, plan):
    now = utcnow()
    doc = {
        "userId": user_oid,
        "planId": plan["_id"],
        "status": ACTIVE,
        "startedAt": now,
        "expiresAt": now + timedelta(days=plan.get("ForDays", 0)),
        "limits": {"articles": plan.get("articalsNumber", 0), "topics": plan.get("maxTopics", 0)},
        "usage": {"articles": 0, "topics": 0},
        "createdAt": now,
        "updatedAt": now,
    }
    doc["_id"] = db().usersubscriptions.insert_one(doc).inserted_id
    return doc


def ensure_free(user_id):
    """Give a store its Free plan once. Old stores missed this because of an argument swap."""
    user_oid = oid(user_id, "User")
    if db().usersubscriptions.find_one({"userId": user_oid}):
        return
    plan = db().plans.find_one({"name": "Free", "isActive": True})
    if plan:
        _insert(user_oid, plan)


def active(user_id):
    sub = db().usersubscriptions.find_one(
        {"userId": oid(user_id, "User"), "status": ACTIVE}, sort=[("startedAt", -1)]
    )
    if not sub:
        return None
    if as_utc(sub["expiresAt"]) < utcnow():
        db().usersubscriptions.update_one(
            {"_id": sub["_id"]}, {"$set": {"status": EXPIRED, "updatedAt": utcnow()}}
        )
        return None
    return sub


def require_active(user_id):
    sub = active(user_id)
    if not sub:
        raise ApiError(403, "No active subscription. Please choose a plan.", code="NO_SUBSCRIPTION")
    return sub


def remaining(sub, feature):
    return max(0, sub["limits"].get(feature, 0) - sub.get("usage", {}).get(feature, 0))


def reserve(user_id, feature, count=1):
    """Atomically take from the plan's allowance, so parallel requests cannot exceed it."""
    sub = require_active(user_id)
    limit = sub["limits"].get(feature, 0)
    updated = db().usersubscriptions.update_one(
        {"_id": sub["_id"], f"usage.{feature}": {"$lte": limit - count}},
        {"$inc": {f"usage.{feature}": count}, "$set": {"updatedAt": utcnow()}},
    )
    if updated.modified_count != 1:
        raise ApiError(
            403,
            f"Your {feature} limit has been reached. Please upgrade your plan.",
            code="LIMIT_REACHED",
        )
    return sub["_id"]


def release(subscription_id, feature, count=1):
    if count > 0:
        db().usersubscriptions.update_one(
            {"_id": subscription_id, f"usage.{feature}": {"$gte": count}},
            {"$inc": {f"usage.{feature}": -count}},
        )


def plan_for(sub):
    return db().plans.find_one({"_id": sub["planId"]}) or {}


def me(user_id):
    sub = active(user_id)
    if not sub:
        raise ApiError(404, "Subscription not found.", code="NO_SUBSCRIPTION")
    seconds = (as_utc(sub["expiresAt"]) - utcnow()).total_seconds()
    return {
        **sub,
        "planId": plan_for(sub),
        "isActive": True,
        "remaining": {feature: remaining(sub, feature) for feature in FEATURES},
        "remainingDays": max(0, math.ceil(seconds / 86400)),
    }


def assign_plan(user_id, plan_id):
    """Admin only: replace a user's active subscription."""
    plan = db().plans.find_one({"_id": oid(plan_id, "Plan")})
    if not plan:
        raise ApiError(404, "Plan not found.")
    if not plan.get("isActive"):
        raise ApiError(400, "Selected plan is inactive.")
    user_oid = oid(user_id, "User")
    if not db().users.find_one({"_id": user_oid}):
        raise ApiError(404, "User not found.")
    db().usersubscriptions.update_many(
        {"userId": user_oid, "status": ACTIVE},
        {"$set": {"status": EXPIRED, "updatedAt": utcnow()}},
    )
    return _insert(user_oid, plan)


def toggle(subscription_id):
    sub = db().usersubscriptions.find_one({"_id": oid(subscription_id, "Subscription")})
    if not sub:
        raise ApiError(404, "Subscription not found.")
    status = CANCELLED if sub.get("status") == ACTIVE else ACTIVE
    db().usersubscriptions.update_one(
        {"_id": sub["_id"]}, {"$set": {"status": status, "updatedAt": utcnow()}}
    )
    sub["status"] = status
    return sub


def expire_overdue():
    return db().usersubscriptions.update_many(
        {"status": ACTIVE, "expiresAt": {"$lt": utcnow()}},
        {"$set": {"status": EXPIRED, "updatedAt": utcnow()}},
    ).modified_count
