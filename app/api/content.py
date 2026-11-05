"""Blogs, publishing and hero images."""
from flask import Blueprint, g, jsonify, request

from ..core import ApiError, body, int_arg, require_auth, string_field, string_list
from ..services import blogs, publishing

bp = Blueprint("content", __name__)
STATUSES = {"GENERATING", "IMAGE_PENDING", "IMAGE_GENERATING", "COMPLETED", "PUBLISHED", "SCHEDULED", "FAILED"}


def _store():
    return g.user["integrationId"]


@bp.get("/blog/all")
@require_auth("owner")
def list_all():
    status = request.args.get("status") or None
    if status and status not in STATUSES:
        raise ApiError(400, "Unknown status.")
    return jsonify(
        blogs.list_blogs(_store(), int_arg("page", 1, maximum=100000), int_arg("limit", 10),
                         request.args.get("search"), status)
    )


@bp.get("/blog")
@require_auth("owner")
def list_active():
    return jsonify(blogs.list_blogs(_store(), 1, 100, status="COMPLETED")["data"])


@bp.post("/blog/generate")
@require_auth("owner")
def generate():
    data = body()
    topic = string_field(data, "topic", required=True, min_len=10, max_len=200)
    return jsonify(blogs.generate(_store(), g.user["userId"], topic.strip(), string_list(data, "products", 10)))


@bp.post("/blog/generate-campaign")
@require_auth("owner")
def generate_campaign():
    data = body()
    competitor = string_field(data, "competitorUrl", required=True, max_len=500)
    calendar = data.get("calendar")
    if not isinstance(calendar, dict):
        raise ApiError(400, "calendar is required.")
    keywords = data.get("keywords") or {}
    if not isinstance(keywords, dict):
        raise ApiError(400, "keywords has an invalid value.")
    return jsonify(
        blogs.generate_campaign(
            _store(),
            g.user["userId"],
            {
                "competitorUrl": competitor,
                "calendar": {
                    "type": string_field(calendar, "type", required=True, max_len=50),
                    "name": string_field(calendar, "name", required=True, max_len=200),
                    "country": string_field(calendar, "country", max_len=100),
                },
                "collections": string_list(data, "collections", 10),
                "products": string_list(data, "products", 20),
                "shortTail": string_list(keywords, "shortTail", 20),
                "longTail": string_list(keywords, "longTail", 50),
            },
        )
    )


@bp.patch("/blog/<blog_id>/update")
@require_auth("owner")
def update(blog_id):
    return jsonify(blogs.update(_store(), blog_id, body()))


@bp.post("/blog/<blog_id>/draft")
@require_auth("owner")
def save_draft(blog_id):
    return jsonify(blogs.save_draft(_store(), blog_id, body()))


@bp.post("/publish/<blog_id>")
@require_auth("owner")
def publish(blog_id):
    return jsonify(publishing.publish(_store(), blog_id, body()))


@bp.post("/publish/<blog_id>/schedule")
@require_auth("owner")
def schedule(blog_id):
    return jsonify(publishing.schedule(_store(), g.user["userId"], blog_id, body()))


@bp.delete("/publish/schedule/<blog_id>")
@require_auth("owner")
def cancel_schedule(blog_id):
    return jsonify(publishing.cancel_schedule(_store(), blog_id))


@bp.post("/image/generate/<blog_id>")
@require_auth("owner")
def regenerate_image(blog_id):
    blog = blogs.regenerate_image(_store(), blog_id)
    return jsonify(success=True, message="Hero image generated successfully.", blog=blog)
