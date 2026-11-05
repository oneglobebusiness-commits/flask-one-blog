"""Login, Shopify install, integrations, plans and subscriptions."""
import hashlib
import hmac
from datetime import timedelta
from urllib.parse import urlencode

import jwt
import requests
from flask import Blueprint, current_app, g, jsonify, redirect, request

from .. import limiter
from ..core import ApiError, body, db, oid, require_auth, sign_token, string_field, utcnow
from ..services import shopify, subscriptions
from ..services.seed import DEFAULT_ADMIN_PASSWORD, check_password

bp = Blueprint("accounts", __name__)


def _public(document):
    """Remove secrets before a user or integration leaves the server."""
    return {k: v for k, v in document.items() if k not in ("password", "accessToken")}


def _shopify_settings():
    config = current_app.config
    if not config["SHOPIFY_API_KEY"] or not config["SHOPIFY_API_SECRET"]:
        raise ApiError(500, "Shopify credentials are not configured on the server.")
    return config


def _install_url(shop):
    config = _shopify_settings()
    if not config["SHOPIFY_CALLBACK_URL"]:
        raise ApiError(500, "SHOPIFY_CALLBACK_URL is not configured on the server.")
    state = jwt.encode(
        {"shop": shop, "purpose": "shopify-install", "exp": utcnow() + timedelta(minutes=10)},
        config["JWT_SECRET"],
        algorithm="HS256",
    )
    query = urlencode(
        {
            "client_id": config["SHOPIFY_API_KEY"],
            "scope": config["SHOPIFY_SCOPES"],
            "redirect_uri": config["SHOPIFY_CALLBACK_URL"],
            "state": state,
        }
    )
    return f"https://{shop}/admin/oauth/authorize?{query}"


def _verify_session_token(token):
    config = _shopify_settings()
    try:
        claims = jwt.decode(
            token,
            config["SHOPIFY_API_SECRET"],
            algorithms=["HS256"],
            audience=config["SHOPIFY_API_KEY"],
            leeway=10,
            options={"require": ["exp", "nbf", "iss", "dest", "aud", "sub"]},
        )
    except jwt.PyJWTError:
        raise ApiError(401, "Invalid Shopify token")
    shop = claims["dest"].replace("https://", "")
    issuer = claims["iss"].replace("https://", "").split("/")[0]
    if not shopify.valid_shop(shop) or issuer != shop:
        raise ApiError(401, "Invalid Shopify token")
    return shop, claims["sub"]


@bp.post("/auth/shopify")
@limiter.limit("30/minute")
def shopify_login():
    id_token = string_field(body(), "idToken", required=True)
    shop, shopify_user_id = _verify_session_token(id_token)

    integration = db().integrations.find_one({"storeUrl": shop})
    if not integration or not integration.get("accessToken"):
        raise ApiError(409, "This store needs to install the app.", needsInstall=True,
                       installUrl=_install_url(shop))

    now = utcnow()
    user = db().users.find_one({"shopDomain": shop})
    if not user:
        user = {
            "shopDomain": shop,
            "shopifyUserId": shopify_user_id,
            "role": "owner",
            "integrationId": str(integration["_id"]),
            "isActive": True,
            "createdAt": now,
            "updatedAt": now,
        }
        user["_id"] = db().users.insert_one(user).inserted_id
    subscriptions.ensure_free(user["_id"])

    token = sign_token(
        {
            "userId": str(user["_id"]),
            "role": "owner",
            "integrationId": str(integration["_id"]),
            "shopDomain": shop,
        }
    )
    return jsonify(accessToken=token, user=_public(user), integration=_public(integration))


@bp.post("/auth/admin")
@limiter.limit("10/minute")
def admin_login():
    data = body()
    email = string_field(data, "email", required=True)
    password = string_field(data, "password", required=True)
    admin = db().users.find_one({"email": email, "role": "admin", "isActive": {"$ne": False}})
    invalid = ApiError(401, "Invalid email or password")
    if not admin or not check_password(password, admin.get("password")):
        raise invalid
    if password == DEFAULT_ADMIN_PASSWORD:
        raise ApiError(403, "The default admin password is disabled. Set ADMIN_PASSWORD and restart the server.")
    token = sign_token({"userId": str(admin["_id"]), "role": "admin"})
    return jsonify(
        accessToken=token, user={"id": admin["_id"], "email": admin["email"], "role": "admin"}
    )


@bp.route("/integrations/shopify/install", methods=["GET", "POST"])
@limiter.limit("30/minute")
def install_shopify():
    shop = request.args.get("shop") if request.method == "GET" else body().get("shop")
    if not isinstance(shop, str) or not shopify.valid_shop(shop):
        raise ApiError(400, "A valid *.myshopify.com shop is required.")
    url = _install_url(shop)
    return redirect(url) if request.method == "GET" else jsonify(installUrl=url)


def _valid_hmac(args, secret):
    supplied = args.get("hmac", "")
    pairs = sorted((k, v) for k, v in args.items() if k != "hmac")
    message = "&".join(f"{k}={v}" for k, v in pairs)
    digest = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, supplied)


@bp.get("/integrations/shopify/callback")
@limiter.limit("30/minute")
def shopify_callback():
    config = _shopify_settings()
    shop = request.args.get("shop", "")
    code = request.args.get("code", "")
    # These checks run before the app secret is sent anywhere.
    if not shopify.valid_shop(shop) or not code:
        raise ApiError(400, "Invalid Shopify callback.")
    if not _valid_hmac(request.args, config["SHOPIFY_API_SECRET"]):
        raise ApiError(401, "Invalid Shopify signature.")
    try:
        state = jwt.decode(request.args.get("state", ""), config["JWT_SECRET"], algorithms=["HS256"])
    except jwt.PyJWTError:
        raise ApiError(401, "Invalid or expired install request.")
    if state.get("purpose") != "shopify-install" or state.get("shop") != shop:
        raise ApiError(401, "Invalid or expired install request.")

    try:
        token_response = requests.post(
            f"https://{shop}/admin/oauth/access_token",
            json={
                "client_id": config["SHOPIFY_API_KEY"],
                "client_secret": config["SHOPIFY_API_SECRET"],
                "code": code,
            },
            timeout=30,
        )
        token_response.raise_for_status()
        access_token = token_response.json()["access_token"]
        store_response = requests.get(
            f"https://{shop}/admin/api/{config['SHOPIFY_API_VERSION']}/shop.json",
            headers={"X-Shopify-Access-Token": access_token},
            timeout=30,
        )
        store_response.raise_for_status()
        store = store_response.json()["shop"]
    except (requests.RequestException, KeyError, ValueError) as err:
        raise ApiError(502, "Could not finish connecting to Shopify.") from err

    now = utcnow()
    db().integrations.update_one(
        {"storeUrl": shop},
        {
            "$set": {
                "platform": "shopify",
                "storeName": store.get("name") or shop,
                "shopId": str(store.get("id", "")),
                "email": store.get("email"),
                "country": store.get("country_name"),
                "currency": store.get("currency"),
                "domain": store.get("domain"),
                "myshopifyDomain": store.get("myshopify_domain"),
                "accessToken": access_token,
                "isActive": True,
                "updatedAt": now,
            },
            "$setOnInsert": {"createdAt": now},
        },
        upsert=True,
    )
    return redirect(f"https://{shop}/admin/apps/{config['SHOPIFY_API_KEY']}")


INTEGRATION_FIELDS = ("platform", "storeName", "storeUrl", "accessToken", "shopId", "isActive")


@bp.get("/integrations")
@require_auth("admin")
def list_integrations():
    return jsonify([_public(i) for i in db().integrations.find().sort("createdAt", -1)])


@bp.post("/integrations")
@require_auth("admin")
def create_integration():
    data = body()
    now = utcnow()
    doc = {k: data[k] for k in INTEGRATION_FIELDS if k in data}
    if doc.get("platform") not in ("shopify", "wordpress") or not doc.get("storeName") or not doc.get("storeUrl"):
        raise ApiError(400, "platform, storeName and storeUrl are required.")
    doc.update(createdAt=now, updatedAt=now)
    doc["_id"] = db().integrations.insert_one(doc).inserted_id
    return jsonify(_public(doc)), 201


def _integration(integration_id):
    integration = db().integrations.find_one({"_id": oid(integration_id, "Integration")})
    if not integration:
        raise ApiError(404, "Integration not found")
    return integration


@bp.get("/integrations/<integration_id>")
@require_auth("admin")
def get_integration(integration_id):
    return jsonify(_public(_integration(integration_id)))


@bp.patch("/integrations/<integration_id>")
@require_auth("admin")
def update_integration(integration_id):
    integration = _integration(integration_id)
    data = body()
    changes = {k: data[k] for k in INTEGRATION_FIELDS if k in data}
    changes["updatedAt"] = utcnow()
    db().integrations.update_one({"_id": integration["_id"]}, {"$set": changes})
    return jsonify(_public(_integration(integration_id)))


@bp.delete("/integrations/<integration_id>")
@require_auth("admin")
def delete_integration(integration_id):
    db().integrations.delete_one({"_id": _integration(integration_id)["_id"]})
    return jsonify(message="Integration removed successfully")


PLAN_FIELDS = {
    "name": str, "price": (int, float), "ForDays": int, "articalsNumber": int, "maxTopics": int,
    "maxStores": int, "analyticsEnabled": bool, "scheduleEnabled": bool, "isActive": bool,
}
OWNER_PLAN_PROJECTION = {
    "name": 1, "price": 1, "ForDays": 1, "analyticsEnabled": 1, "articalsNumber": 1,
    "maxTopics": 1, "maxStores": 1, "scheduleEnabled": 1,
}


def _plan_data(data):
    clean = {}
    for key, kind in PLAN_FIELDS.items():
        if key in data:
            value = data[key]
            if not isinstance(value, kind) or (kind is not bool and isinstance(value, bool)):
                raise ApiError(400, f"{key} has an invalid value.")
            clean[key] = value
    return clean


@bp.get("/plans")
@require_auth("admin", "owner")
def list_plans():
    if g.user["role"] == "admin":
        return jsonify(list(db().plans.find()))
    return jsonify(list(db().plans.find({"isActive": True}, OWNER_PLAN_PROJECTION).sort("price", 1)))


@bp.post("/plans")
@require_auth("admin")
def create_plan():
    data = _plan_data(body())
    for key in ("name", "ForDays", "articalsNumber"):
        if key not in data:
            raise ApiError(400, f"{key} is required.")
    now = utcnow()
    plan = {"price": 0, "maxTopics": 30, "maxStores": 1, "analyticsEnabled": False,
            "scheduleEnabled": False, "isActive": True, **data, "createdAt": now, "updatedAt": now}
    plan["_id"] = db().plans.insert_one(plan).inserted_id
    return jsonify(plan), 201


@bp.get("/plans/<plan_id>")
@require_auth("admin", "owner")
def get_plan(plan_id):
    query = {"_id": oid(plan_id, "Plan")}
    projection = None
    if g.user["role"] != "admin":
        query["isActive"] = True
        projection = OWNER_PLAN_PROJECTION
    plan = db().plans.find_one(query, projection)
    if not plan:
        raise ApiError(404, "Plan not found")
    return jsonify(plan)


@bp.patch("/plans/<plan_id>")
@require_auth("admin")
def update_plan(plan_id):
    changes = _plan_data(body())
    changes["updatedAt"] = utcnow()
    result = db().plans.update_one({"_id": oid(plan_id, "Plan")}, {"$set": changes})
    if not result.matched_count:
        raise ApiError(404, "Plan not found")
    return jsonify(db().plans.find_one({"_id": oid(plan_id)}))


@bp.patch("/plans/toggle/<plan_id>")
@require_auth("admin")
def toggle_plan(plan_id):
    plan = db().plans.find_one({"_id": oid(plan_id, "Plan")})
    if not plan:
        raise ApiError(404, "Plan not found")
    active = not plan.get("isActive")
    db().plans.update_one({"_id": plan["_id"]}, {"$set": {"isActive": active, "updatedAt": utcnow()}})
    plan["isActive"] = active
    return jsonify(message=f"Plan {'activated' if active else 'deactivated'} successfully", data=plan)


@bp.get("/user-subscription/me")
@require_auth("owner")
def my_subscription():
    return jsonify(subscriptions.me(g.user["userId"]))


@bp.patch("/user-subscription/upgrade/<plan_id>")
@require_auth("owner")
def upgrade(plan_id):
    # Paid plans need the Shopify Billing API. Until it exists, nobody gets one for free.
    raise ApiError(501, "Online payment is not connected yet. Please contact support to change your plan.",
                   code="BILLING_NOT_CONNECTED")


@bp.post("/user-subscription/<user_id>/<plan_id>")
@require_auth("admin")
def assign_subscription(user_id, plan_id):
    return jsonify(subscriptions.assign_plan(user_id, plan_id)), 201


@bp.patch("/user-subscription/toggle/<subscription_id>")
@require_auth("admin")
def toggle_subscription(subscription_id):
    return jsonify(subscriptions.toggle(subscription_id))
