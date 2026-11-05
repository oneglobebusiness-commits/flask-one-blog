import hashlib
import hmac
from urllib.parse import urlencode

import bcrypt
import requests

from app.api import accounts
from app.services.seed import run_seeds

from .conftest import API_SECRET, session_token


def test_integrations_need_admin_and_never_return_tokens(client, store, admin_headers):
    assert client.get("/api/v1/integrations").status_code == 401
    assert client.get("/api/v1/integrations", headers=store["headers"]).status_code == 403
    assert client.delete(f"/api/v1/integrations/{store['id']}").status_code == 401
    response = client.get("/api/v1/integrations", headers=admin_headers)
    assert response.status_code == 200
    assert "shpat_secret" not in response.get_data(as_text=True)


def test_forged_shopify_token_is_rejected(client, store):
    forged = session_token(secret="attacker-secret-attacker-secret!")
    assert client.post("/api/v1/auth/shopify", json={"idToken": forged}).status_code == 401
    wrong_aud = session_token(aud="another-app")
    assert client.post("/api/v1/auth/shopify", json={"idToken": wrong_aud}).status_code == 401


def test_real_login_hides_token_and_gives_new_store_free_plan(client, database, store):
    database.users.delete_many({})
    database.usersubscriptions.delete_many({})
    response = client.post("/api/v1/auth/shopify", json={"idToken": session_token()})
    assert response.status_code == 200
    assert "shpat_secret" not in response.get_data(as_text=True)
    token = response.get_json()["accessToken"]
    plan = client.get("/api/v1/user-subscription/me", headers={"Authorization": f"Bearer {token}"})
    assert plan.status_code == 200
    assert plan.get_json()["planId"]["name"] == "Free"
    assert plan.get_json()["remaining"]["articles"] == 1


def test_uninstalled_store_gets_install_link(client):
    response = client.post("/api/v1/auth/shopify", json={"idToken": session_token("new.myshopify.com")})
    assert response.status_code == 409
    assert response.get_json()["installUrl"].startswith("https://new.myshopify.com/admin/oauth/authorize")


def _signed(params):
    message = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    params = dict(params, hmac=hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest())
    return "/api/v1/integrations/shopify/callback?" + urlencode(params)


def test_callback_never_sends_secret_to_unverified_host(client, monkeypatch):
    sent = []
    monkeypatch.setattr(requests, "post", lambda *a, **k: sent.append(a) or None)
    assert client.get("/api/v1/integrations/shopify/callback?shop=evil.example&code=x").status_code == 400
    unsigned = "/api/v1/integrations/shopify/callback?shop=demo.myshopify.com&code=x&hmac=bad"
    assert client.get(unsigned).status_code == 401
    no_state = _signed({"shop": "demo.myshopify.com", "code": "x", "state": "bad"})
    assert client.get(no_state).status_code == 401
    assert sent == []


def test_default_admin_password_is_disabled(client, database):
    database.users.insert_one(
        {"email": "admin@blog1.ai", "role": "admin", "isActive": True,
         "password": bcrypt.hashpw(b"Admin@123", bcrypt.gensalt(4)).decode()}
    )
    response = client.post("/api/v1/auth/admin", json={"email": "admin@blog1.ai", "password": "Admin@123"})
    assert response.status_code == 403


def test_admin_password_replaced_from_environment(app, client, database):
    database.users.insert_one(
        {"email": "admin@blog1.ai", "role": "admin", "isActive": True,
         "password": bcrypt.hashpw(b"Admin@123", bcrypt.gensalt(4)).decode()}
    )
    app.config["ADMIN_PASSWORD"] = "a-new-strong-password"
    with app.app_context():
        run_seeds()
    response = client.post("/api/v1/auth/admin", json={"email": "admin@blog1.ai", "password": "a-new-strong-password"})
    assert response.status_code == 200


def test_owner_cannot_use_raw_ai_or_read_keys(client, store, admin_headers):
    assert client.post("/api/v1/ai/generate", json={"prompt": "x"}, headers=store["headers"]).status_code == 403
    assert client.get("/api/v1/ai/providers", headers=store["headers"]).status_code == 403
    assert "gemini-secret" not in client.get("/api/v1/ai/providers", headers=admin_headers).get_data(as_text=True)


def test_country_event_changes_need_admin(client, store):
    assert client.post("/api/v1/country-events", json={"country": "X"}, headers=store["headers"]).status_code == 403
    assert client.get("/api/v1/country-events").status_code == 401


def test_owner_cannot_touch_another_stores_blog(client, database, store, monkeypatch):
    from app.services import ai

    called = []
    monkeypatch.setattr(ai, "generate_image", lambda p: called.append(p) or b"x")
    other = database.blogs.insert_one(
        {"integrationId": "another-store", "topic": "t", "title": "t", "content": "<p>x</p>", "heroImagePrompt": "p"}
    ).inserted_id
    assert client.post(f"/api/v1/image/generate/{other}", headers=store["headers"]).status_code == 404
    assert client.post(f"/api/v1/publish/{other}", json={}, headers=store["headers"]).status_code == 404
    assert client.post(f"/api/v1/blog/{other}/draft", json={"title": "h"}, headers=store["headers"]).status_code == 404
    assert called == []


def test_scripts_are_removed_and_paths_hidden(client, database, store):
    from .conftest import make_blog

    make_blog(database, store["id"], content='<p onclick="x()">ok</p><script>alert(1)</script>',
              heroImage={"url": "/uploads/a.png", "localPath": "/secret/a.png"})
    text = client.get("/api/v1/blog/all", headers=store["headers"]).get_data(as_text=True)
    assert "alert(1)" not in text and "onclick" not in text and "/secret/" not in text


def test_search_with_regex_characters_works(client, database, store):
    from .conftest import make_blog

    make_blog(database, store["id"], title="Shoes (2026)")
    response = client.get("/api/v1/blog/all", query_string={"search": "(2026"}, headers=store["headers"])
    assert response.status_code == 200
    assert response.get_json()["pagination"]["total"] == 1


def test_security_headers_allow_shopify_framing(client):
    csp = client.get("/welcome").headers["Content-Security-Policy"]
    assert "frame-ancestors https://admin.shopify.com" in csp and "script-src 'self'" in csp


def test_accounts_module_keeps_secret_out_of_public_helper():
    assert "accessToken" not in accounts._public({"accessToken": "x", "storeName": "y"})
