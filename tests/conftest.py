from datetime import timedelta

import jwt
import mongomock
import pytest

from app import create_app
from app.core import sign_token, utcnow

API_KEY = "test-key"
API_SECRET = "test-shopify-secret"


@pytest.fixture
def app(tmp_path):
    client = mongomock.MongoClient(tz_aware=True)
    application = create_app(
        {
            "TESTING": True,
            "JWT_SECRET": "test-jwt-secret",
            "MONGO_CLIENT": client,
            "MONGO_DB": "test",
            "SHOPIFY_API_KEY": API_KEY,
            "SHOPIFY_API_SECRET": API_SECRET,
            "SHOPIFY_SCOPES": "read_products",
            "SHOPIFY_CALLBACK_URL": "https://app.example/api/v1/integrations/shopify/callback",
            "UPLOAD_DIR": str(tmp_path),
            "ENABLE_SCHEDULER": False,
            "ADMIN_EMAIL": "",
            "ADMIN_PASSWORD": "",
        }
    )
    from app import limiter

    limiter.enabled = False
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def database(app):
    return app.extensions["mongo_db"]


def session_token(shop="demo.myshopify.com", secret=API_SECRET, aud=API_KEY):
    now = utcnow()
    return jwt.encode(
        {
            "iss": f"https://{shop}/admin",
            "dest": f"https://{shop}",
            "aud": aud,
            "sub": "42",
            "exp": now + timedelta(minutes=1),
            "nbf": now - timedelta(seconds=5),
            "iat": now,
        },
        secret,
        algorithm="HS256",
    )


@pytest.fixture
def store(app, database):
    """A connected store with an owner on a paid-style plan, plus its analysis."""
    now = utcnow()
    integration_id = database.integrations.insert_one(
        {"platform": "shopify", "storeName": "Demo", "storeUrl": "demo.myshopify.com", "accessToken": "shpat_secret"}
    ).inserted_id
    user_id = database.users.insert_one(
        {"shopDomain": "demo.myshopify.com", "role": "owner", "integrationId": str(integration_id)}
    ).inserted_id
    plan_id = database.plans.insert_one(
        {"name": "Pro", "price": 10, "ForDays": 30, "articalsNumber": 2, "maxTopics": 3,
         "scheduleEnabled": True, "isActive": True}
    ).inserted_id
    database.usersubscriptions.insert_one(
        {"userId": user_id, "planId": plan_id, "status": "active", "startedAt": now,
         "expiresAt": now + timedelta(days=30), "limits": {"articles": 2, "topics": 3},
         "usage": {"articles": 0, "topics": 0}}
    )
    database.storeintelligences.insert_one(
        {"integrationId": integration_id, "shopDomain": "demo.myshopify.com", "niche": "Shoes",
         "primaryMarket": ["India"], "blogTopics": [{"title": "Old topic"}]}
    )
    database.ai_providers.insert_one(
        {"provider": "gemini", "displayName": "Gemini", "modelName": "m", "apiKey": "gemini-secret",
         "isDefault": True, "isActive": True, "maxTokens": 4096}
    )
    with app.app_context():
        token = sign_token({"userId": str(user_id), "role": "owner", "integrationId": str(integration_id),
                            "shopDomain": "demo.myshopify.com"})
    return {"id": str(integration_id), "user": user_id, "plan": plan_id,
            "headers": {"Authorization": f"Bearer {token}"}}


@pytest.fixture
def admin_headers(app):
    with app.app_context():
        token = sign_token({"userId": "507f1f77bcf86cd799439011", "role": "admin"})
    return {"Authorization": f"Bearer {token}"}


def make_blog(database, integration_id, **fields):
    now = utcnow()
    doc = {"integrationId": integration_id, "topic": "A topic for tests", "title": "Title",
           "content": "<p>Original</p>", "status": "COMPLETED", "isScheduled": False, "createdAt": now,
           "updatedAt": now, **fields}
    return database.blogs.insert_one(doc).inserted_id
