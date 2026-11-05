import json
import logging
import os
import re

from ..core import ApiError, db, oid, utcnow
from . import ai, shopify, storage, subscriptions
from .html_clean import clean_html

log = logging.getLogger(__name__)
BLOG_TOKENS = 16384
EDITABLE = ("title", "content", "slug", "metaTitle", "metaDescription", "excerpt", "keywords")
PROMPT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")


def blog_out(blog):
    """Public form of a blog: safe HTML and no server file paths."""
    output = dict(blog)
    output["content"] = clean_html(blog.get("content"))
    if output.get("heroImage"):
        output["heroImage"] = {k: v for k, v in output["heroImage"].items() if k != "localPath"}
    return output


def _prompt(name, values):
    with open(os.path.join(PROMPT_DIR, name), encoding="utf8") as handle:
        text = handle.read()
    # One pass, so a placeholder inside merchant text is never expanded.
    return re.sub(r"\{\{(\w+)\}\}", lambda m: str(values[m.group(1)]), text)


def _pretty(value):
    return json.dumps(value, indent=2, ensure_ascii=False)


def _intelligence(integration_id):
    intelligence = db().storeintelligences.find_one({"integrationId": oid(integration_id, "Store")})
    if not intelligence:
        raise ApiError(404, "Store analysis not found. Please analyze your store first.")
    return intelligence


def get_owned(integration_id, blog_id):
    blog = db().blogs.find_one({"_id": oid(blog_id, "Blog"), "integrationId": integration_id})
    if not blog:
        raise ApiError(404, "Blog not found.")
    return blog


def list_blogs(integration_id, page, limit, search=None, status=None):
    query = {"integrationId": integration_id}
    if search and search.strip():
        pattern = {"$regex": re.escape(search.strip()), "$options": "i"}
        query["$or"] = [{"topic": pattern}, {"title": pattern}]
    if status == "FAILED":
        # A failed publish is recorded in publishStatus.
        query["publishStatus"] = "FAILED"
    elif status:
        query["status"] = status
    total = db().blogs.count_documents(query)
    rows = db().blogs.find(query).sort("createdAt", -1).skip((page - 1) * limit).limit(limit)
    total_pages = (total + limit - 1) // limit
    return {
        "data": [blog_out(row) for row in rows],
        "pagination": {
            "total": total,
            "page": page,
            "limit": limit,
            "totalPages": total_pages,
            "hasNext": page < total_pages,
            "hasPrev": page > 1,
        },
    }


def _attach_hero_image(blog_id):
    """Create the hero image. A failure keeps the written article and reports a warning."""
    blog = db().blogs.find_one({"_id": blog_id})
    warning = None
    update = {"status": "COMPLETED", "updatedAt": utcnow()}
    try:
        if not blog.get("heroImagePrompt"):
            raise ApiError(502, "The AI did not provide an image prompt.")
        update["heroImage"] = storage.save_image(ai.generate_image(blog["heroImagePrompt"]))
    except ApiError as err:
        log.warning("Hero image failed for %s: %s", blog_id, err.message)
        warning = "The article was written, but its hero image could not be generated."
    db().blogs.update_one({"_id": blog_id}, {"$set": update})
    return db().blogs.find_one({"_id": blog_id}), warning


def _create_from_ai(integration_id, topic, generated):
    if not generated.get("title") or not generated.get("content"):
        raise ApiError(502, "The AI response was missing the title or content. Please try again.")
    now = utcnow()
    keywords = generated.get("keywords")
    doc = {
        "integrationId": integration_id,
        "topic": topic or generated["title"],
        "title": generated["title"],
        "slug": generated.get("slug"),
        "metaTitle": generated.get("metaTitle"),
        "metaDescription": generated.get("metaDescription"),
        "excerpt": generated.get("excerpt"),
        "heroImagePrompt": generated.get("heroImagePrompt"),
        "estimatedReadingTime": generated.get("estimatedReadingTime"),
        "keywords": keywords if isinstance(keywords, list) else [],
        "content": clean_html(generated["content"]),
        "status": "IMAGE_PENDING",
        "isScheduled": False,
        "createdAt": now,
        "updatedAt": now,
    }
    return db().blogs.insert_one(doc).inserted_id


def generate(integration_id, user_id, topic, product_ids):
    existing = db().blogs.find_one(
        {"integrationId": integration_id, "topic": topic, "publishStatus": "PUBLISHED"}
    )
    if existing:
        return {"success": True, "topic": topic, "generatedAt": utcnow(), "blog": blog_out(existing),
                "alreadyPublished": True}
    intelligence = _intelligence(integration_id)
    subscription_id = subscriptions.reserve(user_id, "articles")
    try:
        products = shopify.products_by_ids(integration_id, product_ids)
        prompt = _prompt(
            "blog.txt",
            {
                "business_summary": intelligence.get("businessSummary", ""),
                "niche": intelligence.get("niche", ""),
                "brand_voice": intelligence.get("brandVoice", ""),
                "short_tail": _pretty(intelligence.get("shortTailKeywords", [])),
                "long_tail": _pretty(intelligence.get("longTailKeywords", [])),
                "seo_suggestions": _pretty(intelligence.get("seoSuggestions", [])),
                "topic": topic,
                "products": _pretty(products) if products else "No products selected.",
            },
        )
        generated = ai.generate_json(prompt, min_tokens=BLOG_TOKENS)
        blog_id = _create_from_ai(integration_id, topic, generated)
    except Exception:
        subscriptions.release(subscription_id, "articles")
        raise
    blog, warning = _attach_hero_image(blog_id)
    return {"success": True, "topic": topic, "generatedAt": utcnow(), "blog": blog_out(blog), "warning": warning}


def generate_campaign(integration_id, user_id, data):
    intelligence = _intelligence(integration_id)
    subscription_id = subscriptions.reserve(user_id, "articles")
    try:
        collections = shopify.collections_by_ids(integration_id, data["collections"])
        products = shopify.products_by_ids(integration_id, data["products"])
        prompt = _prompt(
            "campaign.txt",
            {
                "business_summary": intelligence.get("businessSummary", ""),
                "niche": intelligence.get("niche", ""),
                "content_pillars": _pretty(intelligence.get("contentPillars", [])),
                "seo_suggestions": _pretty(intelligence.get("seoSuggestions", [])),
                "short_tail": _pretty(intelligence.get("shortTailKeywords", [])),
                "long_tail": _pretty(intelligence.get("longTailKeywords", [])),
                "calendar": _pretty(data["calendar"]),
                "competitor_url": data["competitorUrl"],
                "collections": _pretty(collections) if collections else "No collections selected.",
                "products": _pretty(products) if products else "No products selected.",
                "extra_short_tail": _pretty(data["shortTail"]),
                "extra_long_tail": _pretty(data["longTail"]),
            },
        )
        generated = ai.generate_json(prompt, min_tokens=BLOG_TOKENS)
        blog_id = _create_from_ai(integration_id, None, generated)
    except Exception:
        subscriptions.release(subscription_id, "articles")
        raise
    blog, warning = _attach_hero_image(blog_id)
    return {"success": True, "type": "campaign", "topic": blog["title"], "generatedAt": utcnow(),
            "blog": blog_out(blog), "warning": warning}


def regenerate_image(integration_id, blog_id):
    blog = get_owned(integration_id, blog_id)
    if not blog.get("heroImagePrompt"):
        raise ApiError(400, "This blog has no image prompt.")
    stored = storage.save_image(ai.generate_image(blog["heroImagePrompt"]))
    # A newer image should not be overwritten by an old Shopify URL.
    db().blogs.update_one(
        {"_id": blog["_id"]}, {"$set": {"heroImage": stored, "updatedAt": utcnow()}}
    )
    return blog_out(db().blogs.find_one({"_id": blog["_id"]}))


def clean_edits(data):
    """Keep only editable fields. The old editor sent `html`, so that name is accepted too."""
    edits = {key: data[key] for key in EDITABLE if data.get(key) is not None}
    if data.get("content") is None and data.get("html") is not None:
        edits["content"] = data["html"]
    for key, value in edits.items():
        if key == "keywords":
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise ApiError(400, "keywords must be a list of text values.")
        elif not isinstance(value, str):
            raise ApiError(400, f"{key} must be text.")
    if "content" in edits:
        edits["content"] = clean_html(edits["content"])
        if not re.sub(r"<[^>]+>", "", edits["content"]).strip():
            raise ApiError(400, "Blog content is empty.")
    if "title" in edits:
        edits["title"] = edits["title"].strip()
        if not edits["title"]:
            raise ApiError(400, "Blog title is missing.")
    return edits


def _reject_if_published(blog):
    if blog.get("publishStatus") in ("PUBLISHED", "PUBLISHING"):
        raise ApiError(400, "This blog has already been published or is being published.")


def update(integration_id, blog_id, data):
    blog = get_owned(integration_id, blog_id)
    _reject_if_published(blog)
    edits = clean_edits(data)
    edits["updatedAt"] = utcnow()
    db().blogs.update_one({"_id": blog["_id"]}, {"$set": edits})
    return blog_out(db().blogs.find_one({"_id": blog["_id"]}))


def save_draft(integration_id, blog_id, data):
    """Save edits. A scheduled blog also leaves the schedule and returns to drafts."""
    blog = get_owned(integration_id, blog_id)
    _reject_if_published(blog)
    changes = {"$set": {**clean_edits(data), "updatedAt": utcnow()}}
    if blog.get("status") == "SCHEDULED" or blog.get("isScheduled"):
        changes["$set"].update(status="COMPLETED", isScheduled=False, publishStatus="DRAFT")
        changes["$unset"] = {"scheduledFor": ""}
    db().blogs.update_one({"_id": blog["_id"]}, changes)
    return {
        "success": True,
        "message": "Draft saved successfully.",
        "data": blog_out(db().blogs.find_one({"_id": blog["_id"]})),
    }
