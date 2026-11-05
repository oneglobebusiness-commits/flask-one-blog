import logging
import os

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from pymongo import MongoClient
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from .core import ApiError, JSONProvider, error_response

limiter = Limiter(key_func=get_remote_address, storage_uri="memory://")
log = logging.getLogger(__name__)

CSP = (
    "default-src 'self'; script-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; img-src 'self' data: https:; "
    "connect-src 'self'; object-src 'none'; base-uri 'self'; "
    "frame-ancestors https://admin.shopify.com https://*.myshopify.com"
)


def _flag(name, default):
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes")


def create_app(overrides=None):
    load_dotenv()
    app = Flask(__name__)
    app.json = JSONProvider(app)
    app.json.sort_keys = False
    app.url_map.strict_slashes = False
    app.config.update(
        JWT_SECRET=os.environ.get("JWT_SECRET", ""),
        MONGO_URI=os.environ.get("MONGO_URI", ""),
        MONGO_DB=os.environ.get("MONGO_DB", "test"),
        SHOPIFY_API_KEY=os.environ.get("SHOPIFY_API_KEY", ""),
        SHOPIFY_API_SECRET=os.environ.get("SHOPIFY_API_SECRET", ""),
        SHOPIFY_SCOPES=os.environ.get("SHOPIFY_SCOPES", ""),
        SHOPIFY_CALLBACK_URL=os.environ.get("SHOPIFY_CALLBACK_URL", ""),
        SHOPIFY_API_VERSION=os.environ.get("SHOPIFY_API_VERSION", "2026-04"),
        GEMINI_IMAGE_MODEL=os.environ.get("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-lite-image"),
        ADMIN_EMAIL=os.environ.get("ADMIN_EMAIL", ""),
        ADMIN_PASSWORD=os.environ.get("ADMIN_PASSWORD", ""),
        UPLOAD_DIR=os.path.abspath(os.environ.get("UPLOAD_DIR", "uploads")),
        ENABLE_SCHEDULER=_flag("ENABLE_SCHEDULER", "true"),
        TRUST_PROXY=_flag("TRUST_PROXY", "false"),
        RATELIMIT_ENABLED=True,
        MONGO_CLIENT=None,
    )
    app.config.update(overrides or {})

    if not app.config["JWT_SECRET"]:
        raise RuntimeError("JWT_SECRET must be set.")
    if app.config["TRUST_PROXY"]:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    client = app.config["MONGO_CLIENT"]
    if client is None:
        if not app.config["MONGO_URI"]:
            raise RuntimeError("MONGO_URI must be set.")
        client = MongoClient(app.config["MONGO_URI"], tz_aware=True)
    app.extensions["mongo_db"] = client.get_default_database(default=app.config["MONGO_DB"])

    limiter.init_app(app)

    from .api import register_api
    from .web import web

    register_api(app)
    app.register_blueprint(web)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def handle_http_error(err):
        if request.path.startswith("/api/"):
            return jsonify({"message": err.description}), err.code
        return err

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        log.exception("Unhandled error on %s", request.path)
        return jsonify({"message": "Something went wrong on the server."}), 500

    @app.after_request
    def security_headers(response):
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    from .services.seed import run_seeds

    with app.app_context():
        run_seeds()

    if app.config["ENABLE_SCHEDULER"]:
        from .services.jobs import start_scheduler

        start_scheduler(app)
    return app
