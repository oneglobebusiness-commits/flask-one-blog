from datetime import timedelta

import pytest

from app.core import ApiError, utcnow
from app.services import ai, intelligence, publishing, shopify, storage, subscriptions

from .conftest import make_blog

GENERATED = {"title": "New blog", "slug": "new-blog", "metaTitle": "Meta", "metaDescription": "Desc",
             "excerpt": "Ex", "heroImagePrompt": "picture", "keywords": ["a"], "content": "<h1>New blog</h1><p>Body</p>"}


@pytest.fixture
def fake_ai(monkeypatch):
    monkeypatch.setattr(ai, "generate_json", lambda *a, **k: dict(GENERATED))
    monkeypatch.setattr(ai, "generate_image", lambda prompt: b"png-bytes")
    monkeypatch.setattr(shopify, "products_by_ids", lambda *a: [])


@pytest.fixture
def fake_shopify(monkeypatch):
    sent = []

    def publish_blog(integration_id, blog):
        sent.append(blog)
        return {"blogId": "gid://b", "articleId": "gid://a", "url": "https://demo.myshopify.com/blogs/news/x",
                "handle": "x", "publishedAt": "2026-11-04T10:00:00Z", "imageUrl": None}

    monkeypatch.setattr(shopify, "publish_blog", publish_blog)
    return sent


def usage(database, store):
    return database.usersubscriptions.find_one({"userId": store["user"]})["usage"]


def test_generate_counts_article_and_enforces_limit(client, database, store, fake_ai):
    for topic in ("First long topic", "Second long topic"):
        response = client.post("/api/v1/blog/generate", json={"topic": topic}, headers=store["headers"])
        assert response.status_code == 200
        assert response.get_json()["blog"]["status"] == "COMPLETED"
    assert usage(database, store)["articles"] == 2
    blocked = client.post("/api/v1/blog/generate", json={"topic": "Third long topic"}, headers=store["headers"])
    assert blocked.status_code == 403
    assert blocked.get_json()["code"] == "LIMIT_REACHED"
    campaign = client.post(
        "/api/v1/blog/generate-campaign",
        json={"competitorUrl": "https://x.example", "calendar": {"type": "retail", "name": "Sale"}},
        headers=store["headers"],
    )
    assert campaign.status_code == 403


def test_failed_ai_call_gives_the_article_back(client, database, store, monkeypatch):
    monkeypatch.setattr(shopify, "products_by_ids", lambda *a: [])

    def fail(*a, **k):
        raise ApiError(502, "AI returned invalid JSON. Please try again.")

    monkeypatch.setattr(ai, "generate_json", fail)
    response = client.post("/api/v1/blog/generate", json={"topic": "A long enough topic"}, headers=store["headers"])
    assert response.status_code == 502
    assert usage(database, store)["articles"] == 0


def test_image_failure_keeps_article_as_draft(client, database, store, fake_ai, monkeypatch):
    def fail(prompt):
        raise ApiError(502, "no image")

    monkeypatch.setattr(ai, "generate_image", fail)
    response = client.post("/api/v1/blog/generate", json={"topic": "A long enough topic"}, headers=store["headers"])
    data = response.get_json()
    assert response.status_code == 200 and data["warning"]
    assert data["blog"]["status"] == "COMPLETED"


def test_publish_uses_the_edited_text(client, database, store, fake_shopify):
    blog_id = make_blog(database, store["id"])
    response = client.post(f"/api/v1/publish/{blog_id}", json={"title": "Edited", "content": "<p>Edited body</p>"},
                           headers=store["headers"])
    assert response.status_code == 200
    assert fake_shopify[0]["title"] == "Edited" and "Edited body" in fake_shopify[0]["content"]
    saved = database.blogs.find_one({"_id": blog_id})
    assert saved["status"] == "PUBLISHED" and saved["shopifyUrl"]
    again = client.post(f"/api/v1/publish/{blog_id}", json={}, headers=store["headers"])
    assert again.status_code == 400 and len(fake_shopify) == 1


def test_schedule_saves_edits_then_scheduler_publishes_it(app, client, database, store, fake_shopify):
    blog_id = make_blog(database, store["id"])
    when = (utcnow() + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    response = client.post(f"/api/v1/publish/{blog_id}/schedule",
                           json={"scheduledFor": when, "title": "Scheduled title"}, headers=store["headers"])
    assert response.status_code == 200
    with app.app_context():
        assert publishing.publish_due_blogs() == 0
    database.blogs.update_one({"_id": blog_id}, {"$set": {"scheduledFor": utcnow() - timedelta(minutes=1)}})
    with app.app_context():
        assert publishing.publish_due_blogs() == 1
        assert publishing.publish_due_blogs() == 0
    saved = database.blogs.find_one({"_id": blog_id})
    assert saved["status"] == "PUBLISHED" and saved["isScheduled"] is False
    assert fake_shopify[0]["title"] == "Scheduled title" and len(fake_shopify) == 1


def test_past_schedule_rejected(client, database, store):
    blog_id = make_blog(database, store["id"])
    when = (utcnow() - timedelta(hours=1)).isoformat()
    response = client.post(f"/api/v1/publish/{blog_id}/schedule", json={"scheduledFor": when}, headers=store["headers"])
    assert response.status_code == 400


def test_plan_without_scheduling_is_blocked(client, database, store):
    database.plans.update_one({"_id": store["plan"]}, {"$set": {"scheduleEnabled": False}})
    blog_id = make_blog(database, store["id"])
    when = (utcnow() + timedelta(hours=1)).isoformat()
    response = client.post(f"/api/v1/publish/{blog_id}/schedule", json={"scheduledFor": when}, headers=store["headers"])
    assert response.status_code == 403


def test_move_to_drafts_really_unschedules(app, client, database, store, fake_shopify):
    blog_id = make_blog(database, store["id"], status="SCHEDULED", publishStatus="SCHEDULED", isScheduled=True,
                        scheduledFor=utcnow() - timedelta(minutes=1))
    response = client.post(f"/api/v1/blog/{blog_id}/draft", json={"content": "<p>Kept</p>"}, headers=store["headers"])
    assert response.status_code == 200
    saved = database.blogs.find_one({"_id": blog_id})
    assert saved["status"] == "COMPLETED" and not saved["isScheduled"] and "scheduledFor" not in saved
    with app.app_context():
        assert publishing.publish_due_blogs() == 0


def test_failed_publish_returns_to_drafts_with_error(client, database, store, monkeypatch):
    def fail(*a):
        raise ApiError(502, "Shopify rejected the request.")

    monkeypatch.setattr(shopify, "publish_blog", fail)
    blog_id = make_blog(database, store["id"])
    response = client.post(f"/api/v1/publish/{blog_id}", json={}, headers=store["headers"])
    assert response.status_code == 400
    saved = database.blogs.find_one({"_id": blog_id})
    assert saved["status"] == "COMPLETED" and saved["publishStatus"] == "FAILED" and saved["publishError"]
    listed = client.get("/api/v1/blog/all?status=FAILED", headers=store["headers"]).get_json()
    assert listed["pagination"]["total"] == 1


def test_update_cannot_change_protected_fields(client, database, store):
    blog_id = make_blog(database, store["id"])
    response = client.patch(f"/api/v1/blog/{blog_id}/update",
                            json={"title": "New", "integrationId": "hacked", "status": "PUBLISHED"},
                            headers=store["headers"])
    assert response.status_code == 200
    saved = database.blogs.find_one({"_id": blog_id})
    assert saved["title"] == "New" and saved["integrationId"] == store["id"] and saved["status"] == "COMPLETED"


def test_new_titles_count_against_plan(client, database, store, monkeypatch):
    monkeypatch.setattr(ai, "generate_json", lambda *a, **k: {"blogTopics": [
        {"title": "Fresh one"}, {"title": "Old topic"}, {"title": "Fresh two"}]})
    response = client.post("/api/v1/store-intelligence/topics/generate", json={"reference": "Diwali"},
                           headers=store["headers"])
    data = response.get_json()
    assert response.status_code == 200
    assert [t["title"] for t in data["blogTopics"]] == ["Fresh one", "Fresh two"]
    assert usage(database, store)["topics"] == data["added"]
    assert data["totalTopics"] == 1 + data["added"]


def test_expired_subscription_blocks_generation(client, database, store, fake_ai):
    database.usersubscriptions.update_one({"userId": store["user"]}, {"$set": {"expiresAt": utcnow() - timedelta(days=1)}})
    response = client.post("/api/v1/blog/generate", json={"topic": "A long enough topic"}, headers=store["headers"])
    assert response.status_code == 403
    assert database.usersubscriptions.find_one({"userId": store["user"]})["status"] == "expired"


def test_toggle_subscription_goes_both_ways(app, database, store):
    sub = database.usersubscriptions.find_one({"userId": store["user"]})
    with app.app_context():
        assert subscriptions.toggle(sub["_id"])["status"] == "cancelled"
        assert subscriptions.toggle(sub["_id"])["status"] == "active"


def test_owner_cannot_self_upgrade_for_free(client, store):
    response = client.patch(f"/api/v1/user-subscription/upgrade/{store['plan']}", headers=store["headers"])
    assert response.status_code == 501


def test_plan_lookup_by_id_works_for_owner(client, store):
    response = client.get(f"/api/v1/plans/{store['plan']}", headers=store["headers"])
    assert response.status_code == 200 and response.get_json()["name"] == "Pro"


def test_markets_create_country_calendar_once(client, database, store, monkeypatch):
    calls = []

    def generated(*a, **k):
        calls.append(a)
        return {"seasonal": ["Monsoon"], "cultural": [], "retail": [], "experiential": []}

    monkeypatch.setattr(ai, "generate_json", generated)
    for _ in range(2):
        response = client.post("/api/v1/store-intelligence/primary-market", json={"markets": ["Nepal (NP)"]},
                               headers=store["headers"])
        assert response.status_code == 200
    assert len(calls) == 1
    events = client.get("/api/v1/country-events/Nepal%20(NP)", headers=store["headers"]).get_json()
    assert events["seasonal"] == ["Monsoon"]


def test_analyze_cached_and_string_market_normalised(app, client, database, store, monkeypatch):
    database.storeintelligences.delete_many({})
    monkeypatch.setattr(shopify, "store_context", lambda i: {"shop": {}})
    replies = iter([
        {"niche": "Shoes", "primaryMarket": "India", "shortTailKeywords": ["a", 1]},
        {"blogTopics": [{"title": "T"}, {"keyword": "no title"}]},
        [{"name": "C", "website": "https://c.example"}],
    ])
    monkeypatch.setattr(ai, "generate_json", lambda *a, **k: next(replies))
    response = client.post("/api/v1/store-intelligence/analyze", headers=store["headers"])
    data = response.get_json()
    assert data["primaryMarket"] == ["India"] and data["shortTailKeywords"] == ["a"]
    assert [t["title"] for t in data["blogTopics"]] == ["T"]
    again = client.post("/api/v1/store-intelligence/analyze", headers=store["headers"])
    assert again.status_code == 200


def test_shopify_article_payload_sends_seo_and_no_broken_image(app, database, store, monkeypatch):
    calls = []

    def fake_graphql(integration, query, variables=None):
        calls.append(variables)
        if "blogs(first" in query:
            return {"blogs": {"nodes": []}}
        if "blogCreate" in query:
            return {"blogCreate": {"blog": {"id": "b", "title": "AI Blog", "handle": "ai-blog"}, "userErrors": []}}
        return {"articleCreate": {"article": {"id": "a", "handle": "h", "publishedAt": None}, "userErrors": []}}

    monkeypatch.setattr(shopify, "graphql", fake_graphql)
    with app.app_context():
        shopify.publish_blog(store["id"], {"title": "T", "content": "<h1>T</h1><p>Body</p>", "metaTitle": "MT",
                                           "metaDescription": "MD", "slug": "t"})
    article = calls[-1]["article"]
    assert "undefined" not in article["body"] and "None" not in article["body"]
    assert "image" not in article and "<h1>" not in article["body"]
    assert {m["key"] for m in article["metafields"]} == {"title_tag", "description_tag"}


def test_ai_blog_reused_instead_of_created_again(app, store, monkeypatch):
    queries = []

    def fake_graphql(integration, query, variables=None):
        queries.append(query)
        return {"blogs": {"nodes": [{"id": "b", "title": "AI Blog", "handle": "ai-blog"}]}}

    monkeypatch.setattr(shopify, "graphql", fake_graphql)
    assert shopify._get_or_create_blog({"storeUrl": "x"})["id"] == "b"
    assert not any("blogCreate" in q for q in queries)


def test_max_tokens_cutoff_is_reported(app, database, store, monkeypatch):
    monkeypatch.setattr(ai, "generate_text", lambda *a, **k: {"text": '{"a":', "finishReason": "MAX_TOKENS"})
    with app.app_context(), pytest.raises(ApiError) as caught:
        ai.generate_json("x")
    assert caught.value.status == 502


def test_saved_images_can_be_found_after_server_move(app):
    with app.app_context():
        stored = storage.save_image(b"x")
        assert storage.find_local_image({"fileName": stored["fileName"], "localPath": "/old/server/x.png"})
        assert storage.find_local_image({"fileName": "missing.png", "localPath": "/old/server/x.png"}) is None
