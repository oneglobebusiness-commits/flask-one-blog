"""Store analysis, Shopify catalogue, country events and AI administration."""
from flask import Blueprint, g, jsonify, request

from .. import limiter
from ..core import ApiError, body, db, int_arg, oid, require_auth, string_field, string_list, utcnow
from ..services import ai, intelligence, shopify

bp = Blueprint("store", __name__)


def _store():
    return g.user["integrationId"]


@bp.post("/store-intelligence/analyze")
@require_auth("owner")
def analyze():
    force = request.args.get("forceRefresh", "").lower() == "true"
    return jsonify(intelligence.analyze(_store(), g.user["shopDomain"], force))


@bp.get("/store-intelligence")
@require_auth("owner")
def get_analysis():
    return jsonify(intelligence.get(_store()))


@bp.delete("/store-intelligence")
@require_auth("owner")
def delete_analysis():
    return jsonify(intelligence.delete(_store()))


@bp.post("/store-intelligence/topics/generate")
@require_auth("owner")
def generate_topics():
    data = body()
    count = data.get("count")
    if count is not None and (not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 5):
        raise ApiError(400, "count must be between 1 and 5.")
    reference = string_field(data, "reference", max_len=500)
    return jsonify(intelligence.generate_topics(_store(), g.user["userId"], count, reference))


@bp.post("/store-intelligence/primary-market")
@require_auth("owner")
def primary_market():
    markets = string_list(body(), "markets", 50)
    if not markets:
        raise ApiError(400, "Please add at least one market.")
    return jsonify(intelligence.add_primary_markets(_store(), markets))


@bp.get("/shopify/collections")
@require_auth("owner")
def collections():
    return jsonify(
        shopify.search_collections(_store(), request.args.get("search", ""), int_arg("limit", 20, maximum=100))
    )


@bp.get("/shopify/products")
@require_auth("owner")
def products():
    return jsonify(
        shopify.search_products(
            _store(), request.args.get("search", ""), request.args.get("collection", ""),
            int_arg("limit", 10, maximum=100),
        )
    )


EVENT_FIELDS = ("seasonal", "cultural", "retail", "experiential")


@bp.get("/country-events")
@require_auth("owner", "admin")
def countries():
    rows = db().countryevents.find({}, {"country": 1}).sort("country", 1)
    return jsonify([row["country"] for row in rows])


@bp.get("/country-events/<country>")
@require_auth("owner", "admin")
def events_for_country(country):
    event = intelligence.find_country(country)
    if not event:
        return jsonify({"country": country, **{field: [] for field in EVENT_FIELDS}})
    return jsonify(event)


def _event_fields(data):
    return {field: string_list(data, field, 100) for field in EVENT_FIELDS if field in data}


@bp.post("/country-events")
@require_auth("admin")
def create_event():
    data = body()
    now = utcnow()
    event = {
        "country": string_field(data, "country", required=True, max_len=100).strip(),
        **{field: [] for field in EVENT_FIELDS},
        **_event_fields(data),
        "createdAt": now,
        "updatedAt": now,
    }
    if intelligence.find_country(event["country"]):
        raise ApiError(400, "This country already exists.")
    event["_id"] = db().countryevents.insert_one(event).inserted_id
    return jsonify(event), 201


@bp.patch("/country-events/<event_id>")
@require_auth("admin")
def update_event(event_id):
    data = body()
    changes = {**_event_fields(data), "updatedAt": utcnow()}
    if data.get("country"):
        changes["country"] = string_field(data, "country", max_len=100).strip()
    result = db().countryevents.update_one({"_id": oid(event_id, "Country")}, {"$set": changes})
    if not result.matched_count:
        raise ApiError(404, "Country not found")
    return jsonify(db().countryevents.find_one({"_id": oid(event_id)}))


@bp.delete("/country-events/<event_id>")
@require_auth("admin")
def delete_event(event_id):
    result = db().countryevents.delete_one({"_id": oid(event_id, "Country")})
    if not result.deleted_count:
        raise ApiError(404, "Country not found")
    return jsonify(message="Country deleted successfully")


@bp.post("/ai/generate")
@require_auth("admin")
@limiter.limit("30/minute")
def ai_generate():
    data = body()
    options = data.get("options") if isinstance(data.get("options"), dict) else {}
    return jsonify(
        ai.generate_text(
            string_field(data, "prompt", required=True),
            provider=string_field(data, "provider"),
            model=string_field(data, "modelName"),
            temperature=options.get("temperature"),
            max_tokens=options.get("maxTokens"),
            system_prompts=string_list(data, "systemPrompts", 10) or None,
        )
    )


PROVIDER_FIELDS = ("provider", "displayName", "modelName", "apiKey", "baseUrl", "temperature",
                   "maxTokens", "isActive", "isDefault", "priority", "settings")


def _provider_out(provider):
    """API keys can be set here but are never read back."""
    return {k: v for k, v in provider.items() if k != "apiKey"}


@bp.get("/ai/providers")
@require_auth("admin")
def list_providers():
    return jsonify([_provider_out(p) for p in db().ai_providers.find()])


@bp.post("/ai/providers")
@require_auth("admin")
def create_provider():
    data = body()
    for key in ("provider", "displayName", "modelName", "apiKey"):
        string_field(data, key, required=True)
    now = utcnow()
    doc = {"temperature": 0.7, "maxTokens": 4096, "isActive": True, "isDefault": False, "priority": 1,
           "settings": {}, **{k: data[k] for k in PROVIDER_FIELDS if k in data},
           "createdAt": now, "updatedAt": now}
    if doc["isDefault"]:
        db().ai_providers.update_many({}, {"$set": {"isDefault": False}})
    doc["_id"] = db().ai_providers.insert_one(doc).inserted_id
    return jsonify(_provider_out(doc)), 201


@bp.patch("/ai/providers/<provider_id>")
@require_auth("admin")
def update_provider(provider_id):
    data = body()
    changes = {k: data[k] for k in PROVIDER_FIELDS if k in data}
    changes["updatedAt"] = utcnow()
    if changes.get("isDefault"):
        db().ai_providers.update_many({}, {"$set": {"isDefault": False}})
    result = db().ai_providers.update_one({"_id": oid(provider_id, "AI Provider")}, {"$set": changes})
    if not result.matched_count:
        raise ApiError(404, "AI Provider not found")
    return jsonify(_provider_out(db().ai_providers.find_one({"_id": oid(provider_id)})))


@bp.delete("/ai/providers/<provider_id>")
@require_auth("admin")
def delete_provider(provider_id):
    result = db().ai_providers.delete_one({"_id": oid(provider_id, "AI Provider")})
    if not result.deleted_count:
        raise ApiError(404, "AI Provider not found")
    return jsonify(message="AI Provider deleted")
