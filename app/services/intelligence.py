import json
import re

from ..core import ApiError, db, oid, utcnow
from . import ai, shopify, subscriptions

MAX_MARKETS = 20
LIST_FIELDS = (
    "shortTailKeywords", "longTailKeywords", "customerPainPoints", "customerGoals", "faqIdeas",
    "seoSuggestions", "contentPillars", "aiRecommendations",
)
TEXT_FIELDS = ("niche", "businessSummary", "targetAudience", "brandVoice", "language")

BUSINESS_PROMPT = """You are a world-class Ecommerce Business Consultant.

Analyze this Shopify store.

Store Context

%s

Return ONLY valid JSON.

{"niche":"","businessSummary":"","targetAudience":"","brandVoice":"","language":"","primaryMarket":"",
"customerPainPoints":["","","","",""],"customerGoals":["","","","",""],
"shortTailKeywords":["","","","",""],"longTailKeywords":["","","","",""]}
"""

STRATEGY_PROMPT = """You are an Ecommerce SEO Expert.

Analyze this Shopify store.

Store Context

%s

Return ONLY JSON.

{"contentPillars":["","","","",""],"faqIdeas":["","","","","","","","","",""],
"seoSuggestions":["","","","",""],
"blogTopics":[{"title":"","keyword":"","intent":"","difficulty":"","priority":1}],
"aiRecommendations":["","","","",""]}
"""

COMPETITOR_PROMPT = """You are a professional Ecommerce Market Research Expert.

Using this Shopify Store Context,

%s

Find the TOP 5 competitors.

Return ONLY JSON.

[{"name":"","website":"","description":"","strengths":["","",""],"weaknesses":["","",""]}]
"""

TOPICS_PROMPT = """Generate exactly %(count)d new, distinct SEO blog topic suggestions for this ecommerce store.
%(reference)s
Do not repeat these existing topics:

%(existing)s

Return ONLY valid JSON in this format:

{"blogTopics":[{"title":"","keyword":"","intent":"","difficulty":"","priority":1}]}

Store intelligence:

%(store)s
"""

EVENTS_PROMPT = """Create a country events calendar for %s.

Return ONLY valid JSON.

The response MUST exactly match this schema:

{"seasonal":["string"],"cultural":["string"],"retail":["string"],"experiential":["string"]}

Rules:
- Every property must be an array of strings.
- Do NOT return objects.
- Do NOT include fields like name, period, focus, date, month, or description.
- Each array element must be a single string representing one event or season.
- Include 8-15 relevant entries per category.
- Return ONLY the JSON object.
"""


def _find(integration_id):
    return db().storeintelligences.find_one({"integrationId": oid(integration_id, "Store")})


def _required(integration_id):
    intelligence = _find(integration_id)
    if not intelligence:
        raise ApiError(404, "Store analysis not found. Please analyze your store first.")
    return intelligence


def _strings(value):
    return [v for v in value if isinstance(v, str) and v.strip()] if isinstance(value, list) else []


def _dicts(value):
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def get(integration_id):
    return _find(integration_id)


def analyze(integration_id, shop_domain, force=False):
    cached = _find(integration_id)
    if cached and not force:
        return cached
    context = json.dumps(shopify.store_context(integration_id), indent=2, ensure_ascii=False)
    business = ai.generate_json(BUSINESS_PROMPT % context, temperature=0.3, min_tokens=8192)
    strategy = ai.generate_json(STRATEGY_PROMPT % context, temperature=0.6, min_tokens=8192)
    competitors = ai.generate_json(COMPETITOR_PROMPT % context, temperature=0.4, min_tokens=8192)
    if not isinstance(business, dict) or not isinstance(strategy, dict):
        raise ApiError(502, "AI returned an unexpected analysis. Please try again.")

    merged = {**business, **strategy}
    now = utcnow()
    fields = {key: merged.get(key) or "" for key in TEXT_FIELDS}
    fields.update({key: _strings(merged.get(key)) for key in LIST_FIELDS})
    fields["blogTopics"] = [t for t in _dicts(merged.get("blogTopics")) if t.get("title")]
    fields["competitors"] = _dicts(competitors)
    market = merged.get("primaryMarket")
    fields["primaryMarket"] = _strings(market) if isinstance(market, list) else _strings([market])
    fields["shopDomain"] = shop_domain
    fields["lastAnalyzedAt"] = now
    fields["updatedAt"] = now
    if cached:
        # A refresh keeps the markets the merchant chose.
        if cached.get("primaryMarket"):
            fields.pop("primaryMarket")
    db().storeintelligences.update_one(
        {"integrationId": oid(integration_id, "Store")},
        {"$set": fields, "$setOnInsert": {"createdAt": now}},
        upsert=True,
    )
    return _find(integration_id)


def generate_topics(integration_id, user_id, count=None, reference=None):
    intelligence = _required(integration_id)
    sub = subscriptions.require_active(user_id)
    left = subscriptions.remaining(sub, "topics")
    if left <= 0:
        raise ApiError(403, "Your topics limit has been reached. Please upgrade your plan.",
                       code="LIMIT_REACHED")
    wanted = min(count or 2, left)
    current = intelligence.get("blogTopics") or []
    reference_text = ""
    if reference and reference.strip():
        reference_text = (
            '\nThe user has provided the following context:\n\n"%s"\n\n'
            "Use this as additional guidance while generating the topics.\n\n"
            "The topics must still be relevant to the store's niche, products, audience, and SEO strategy.\n"
            % reference.strip()
        )
    parsed = ai.generate_json(
        TOPICS_PROMPT
        % {
            "count": wanted,
            "reference": reference_text,
            "existing": json.dumps([t.get("title") for t in current], ensure_ascii=False),
            "store": json.dumps(
                {key: intelligence.get(key) for key in
                 ("niche", "businessSummary", "contentPillars", "shortTailKeywords", "longTailKeywords")},
                ensure_ascii=False,
            ),
        },
        min_tokens=4096,
    )
    existing = {(t.get("title") or "").lower() for t in current}
    topics = []
    raw_topics = parsed.get("blogTopics") if isinstance(parsed, dict) else []
    for topic in _dicts(raw_topics):
        title = topic.get("title")
        if isinstance(title, str) and title.strip() and title.lower() not in existing:
            existing.add(title.lower())
            topics.append(topic)
    topics = topics[:wanted]
    if topics:
        subscriptions.reserve(user_id, "topics", len(topics))
        db().storeintelligences.update_one(
            {"_id": intelligence["_id"]},
            {"$set": {"blogTopics": current + topics, "updatedAt": utcnow()}},
        )
    fresh = subscriptions.active(user_id)
    return {
        "success": True,
        "added": len(topics),
        "totalTopics": len(current) + len(topics),
        "remainingTopics": subscriptions.remaining(fresh, "topics") if fresh else 0,
        "blogTopics": topics,
    }


def find_country(country):
    return db().countryevents.find_one(
        {"country": {"$regex": "^%s$" % re.escape(country), "$options": "i"}}
    )


def add_primary_markets(integration_id, markets):
    intelligence = _required(integration_id)
    cleaned = []
    for market in markets:
        name = market.strip()
        if not name:
            continue
        if len(name) > 60:
            raise ApiError(400, "A market name can be at most 60 characters.")
        cleaned.append(name)
    if len(cleaned) > MAX_MARKETS:
        raise ApiError(400, f"You can add at most {MAX_MARKETS} markets.")

    updated, countries = [], []
    for name in cleaned:
        event = find_country(name)
        if not event:
            generated = ai.generate_json(EVENTS_PROMPT % name, min_tokens=4096)
            if not isinstance(generated, dict):
                raise ApiError(502, "AI returned an unexpected calendar. Please try again.")
            now = utcnow()
            event = {
                "country": name,
                "seasonal": _strings(generated.get("seasonal")),
                "cultural": _strings(generated.get("cultural")),
                "retail": _strings(generated.get("retail")),
                "experiential": _strings(generated.get("experiential")),
                "createdAt": now,
                "updatedAt": now,
            }
            event["_id"] = db().countryevents.insert_one(event).inserted_id
        if event["country"].lower() not in [m.lower() for m in updated]:
            updated.append(event["country"])
        countries.append(event)
    db().storeintelligences.update_one(
        {"_id": intelligence["_id"]}, {"$set": {"primaryMarket": updated, "updatedAt": utcnow()}}
    )
    return {"success": True, "primaryMarket": updated, "countryEvents": countries}


def delete(integration_id):
    result = db().storeintelligences.delete_one({"integrationId": oid(integration_id, "Store")})
    return {"acknowledged": True, "deletedCount": result.deleted_count}
