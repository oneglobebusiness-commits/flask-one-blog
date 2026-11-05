import logging
from datetime import datetime, timedelta, timezone

from ..core import ApiError, db, oid, utcnow
from . import blogs, shopify, subscriptions

log = logging.getLogger(__name__)
STUCK_AFTER = timedelta(minutes=10)


def _claim(blog_id, integration_id, extra_filter=None):
    """Atomically mark a blog as publishing, so it cannot be published twice."""
    stuck_before = utcnow() - STUCK_AFTER
    query = {
        "_id": blog_id,
        "integrationId": integration_id,
        "$or": [
            {"publishStatus": {"$nin": ["PUBLISHED", "PUBLISHING"]}},
            {"publishStatus": "PUBLISHING", "publishingAt": {"$lt": stuck_before}},
        ],
    }
    query.update(extra_filter or {})
    return db().blogs.find_one_and_update(
        query,
        {"$set": {"publishStatus": "PUBLISHING", "publishingAt": utcnow(), "publishError": ""}},
        return_document=True,
    )


def _send_to_shopify(blog):
    integration_id = blog["integrationId"]
    try:
        if not blog.get("title"):
            raise ApiError(400, "Blog title is missing.")
        if not (blog.get("content") or "").strip():
            raise ApiError(400, "Blog content is empty.")
        result = shopify.publish_blog(integration_id, blog)
    except Exception as err:
        message = err.message if isinstance(err, ApiError) else "Unexpected publishing error."
        if not isinstance(err, ApiError):
            log.exception("Publishing failed for %s", blog["_id"])
        # The blog returns to drafts with its error showing, so it can be fixed and retried.
        db().blogs.update_one(
            {"_id": blog["_id"]},
            {
                "$set": {
                    "publishStatus": "FAILED",
                    "publishError": message,
                    "status": "COMPLETED",
                    "isScheduled": False,
                    "updatedAt": utcnow(),
                },
                "$unset": {"publishingAt": "", "scheduledFor": ""},
            },
        )
        raise ApiError(400, f"Failed to publish blog to Shopify: {message}") from err

    published_at = _parse_date(result.get("publishedAt")) or utcnow()
    update = {
        "publishStatus": "PUBLISHED",
        "status": "PUBLISHED",
        "publishedAt": published_at,
        "shopifyBlogId": result["blogId"],
        "shopifyArticleId": result["articleId"],
        "shopifyHandle": result["handle"],
        "shopifyUrl": result["url"],
        "publishError": "",
        "isScheduled": False,
        "updatedAt": utcnow(),
    }
    if blog.get("heroImage") and result.get("imageUrl"):
        update["heroImage.shopifyUrl"] = result["imageUrl"]
    db().blogs.update_one(
        {"_id": blog["_id"]},
        {"$set": update, "$unset": {"publishingAt": "", "scheduledFor": ""}},
    )
    _remove_used_topic(blog)
    return db().blogs.find_one({"_id": blog["_id"]})


def _remove_used_topic(blog):
    intelligence = db().storeintelligences.find_one({"integrationId": oid(blog["integrationId"], "Store")})
    if not intelligence or not intelligence.get("blogTopics"):
        return
    topic = (blog.get("topic") or "").lower()
    remaining = [t for t in intelligence["blogTopics"] if (t.get("title") or "").lower() != topic]
    if len(remaining) != len(intelligence["blogTopics"]):
        db().storeintelligences.update_one(
            {"_id": intelligence["_id"]}, {"$set": {"blogTopics": remaining}}
        )


def publish(integration_id, blog_id, data=None):
    blog = blogs.get_owned(integration_id, blog_id)
    if blog.get("publishStatus") == "PUBLISHED":
        raise ApiError(400, "This blog has already been published.")
    edits = blogs.clean_edits(data or {})
    if edits:
        db().blogs.update_one({"_id": blog["_id"]}, {"$set": {**edits, "updatedAt": utcnow()}})
    claimed = _claim(blog["_id"], integration_id)
    if not claimed:
        raise ApiError(400, "This blog is currently being published.")
    published = _send_to_shopify(claimed)
    return {
        "success": True,
        "message": "Blog published successfully.",
        "data": {
            "blogId": published["_id"],
            "publishStatus": published["publishStatus"],
            "publishedAt": published["publishedAt"],
            "shopify": {
                "blogId": published["shopifyBlogId"],
                "articleId": published["shopifyArticleId"],
                "handle": published["shopifyHandle"],
                "url": published["shopifyUrl"],
                "image": (published.get("heroImage") or {}).get("shopifyUrl"),
            },
        },
    }


def _parse_date(value):
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def schedule(integration_id, user_id, blog_id, data):
    blog = blogs.get_owned(integration_id, blog_id)
    if blog.get("publishStatus") in ("PUBLISHED", "PUBLISHING"):
        raise ApiError(400, "This blog has already been published or is being published.")
    when = _parse_date(data.get("scheduledFor"))
    if not when:
        raise ApiError(400, "scheduledFor must be a valid date.")
    if when <= utcnow():
        raise ApiError(400, "Scheduled time must be in the future.")
    sub = subscriptions.require_active(user_id)
    if not subscriptions.plan_for(sub).get("scheduleEnabled"):
        raise ApiError(403, "Your plan does not include scheduling. Please upgrade your plan.",
                       code="PLAN_FEATURE")
    edits = blogs.clean_edits(data)
    db().blogs.update_one(
        {"_id": blog["_id"]},
        {
            "$set": {
                **edits,
                "isScheduled": True,
                "status": "SCHEDULED",
                "publishStatus": "SCHEDULED",
                "scheduledFor": when,
                "publishError": "",
                "updatedAt": utcnow(),
            }
        },
    )
    return {"success": True, "message": "Blog scheduled successfully.", "scheduledFor": when}


def cancel_schedule(integration_id, blog_id):
    blog = blogs.get_owned(integration_id, blog_id)
    if blog.get("publishStatus") != "SCHEDULED":
        raise ApiError(400, "This blog is not scheduled.")
    db().blogs.update_one(
        {"_id": blog["_id"]},
        {
            "$set": {"publishStatus": "DRAFT", "status": "COMPLETED", "isScheduled": False, "updatedAt": utcnow()},
            "$unset": {"scheduledFor": ""},
        },
    )
    return {
        "success": True,
        "message": "Scheduled publishing cancelled.",
        "blog": blogs.blog_out(db().blogs.find_one({"_id": blog["_id"]})),
    }


def publish_due_blogs():
    """Publish scheduled blogs whose time has passed. Returns how many were published."""
    now = utcnow()
    due = list(
        db().blogs.find({"isScheduled": True, "publishStatus": "SCHEDULED", "scheduledFor": {"$lte": now}})
    )
    published = 0
    for blog in due:
        claimed = _claim(blog["_id"], blog["integrationId"], {"publishStatus": "SCHEDULED"})
        if not claimed:
            continue
        try:
            _send_to_shopify(claimed)
            published += 1
        except ApiError as err:
            log.error("Scheduled publish failed for %s: %s", blog["_id"], err.message)
    return published
