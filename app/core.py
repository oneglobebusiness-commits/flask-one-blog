"""Shared helpers: errors, database access, JSON, auth decorators, request validation."""
from datetime import datetime, timedelta, timezone
from functools import wraps

import jwt
from bson import ObjectId
from bson.errors import InvalidId
from flask import current_app, g, jsonify, request
from flask.json.provider import DefaultJSONProvider


class ApiError(Exception):
    def __init__(self, status, message, **extra):
        super().__init__(message)
        self.status = status
        self.message = message
        self.extra = extra


class JSONProvider(DefaultJSONProvider):
    @staticmethod
    def default(o):
        if isinstance(o, ObjectId):
            return str(o)
        if isinstance(o, datetime):
            return as_utc(o).isoformat().replace("+00:00", "Z")
        return DefaultJSONProvider.default(o)


def utcnow():
    return datetime.now(timezone.utc)


def as_utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def db():
    return current_app.extensions["mongo_db"]


def oid(value, label="Record"):
    try:
        return ObjectId(str(value))
    except (InvalidId, TypeError):
        raise ApiError(404, f"{label} not found.")


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(400, "Request body must be a JSON object.")
    return data


def string_field(data, name, required=False, min_len=0, max_len=None):
    value = data.get(name)
    if value is None or value == "":
        if required:
            raise ApiError(400, f"{name} is required.")
        return None
    if not isinstance(value, str):
        raise ApiError(400, f"{name} must be text.")
    if len(value.strip()) < min_len:
        raise ApiError(400, f"{name} must be at least {min_len} characters.")
    if max_len and len(value) > max_len:
        raise ApiError(400, f"{name} must be at most {max_len} characters.")
    return value


def string_list(data, name, max_items):
    value = data.get(name)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ApiError(400, f"{name} must be a list of text values.")
    if len(value) > max_items:
        raise ApiError(400, f"{name} can contain at most {max_items} items.")
    return list(dict.fromkeys(value))


def int_arg(name, default, minimum=1, maximum=100):
    try:
        value = int(request.args.get(name, default))
    except ValueError:
        raise ApiError(400, f"{name} must be a number.")
    return max(minimum, min(value, maximum))


def sign_token(payload):
    now = utcnow()
    claims = dict(payload, iat=now, exp=now + timedelta(days=30))
    return jwt.encode(claims, current_app.config["JWT_SECRET"], algorithm="HS256")


def require_auth(*roles):
    """Require a valid app JWT and, when roles are given, one of those roles."""

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            header = request.headers.get("Authorization", "")
            if not header.startswith("Bearer "):
                raise ApiError(401, "Unauthorized")
            try:
                claims = jwt.decode(
                    header[7:], current_app.config["JWT_SECRET"], algorithms=["HS256"]
                )
            except jwt.PyJWTError:
                raise ApiError(401, "Unauthorized")
            g.user = {
                "userId": claims.get("userId") or claims.get("sub"),
                "role": claims.get("role"),
                "integrationId": claims.get("integrationId"),
                "shopDomain": claims.get("shopDomain"),
            }
            if roles and g.user["role"] not in roles:
                raise ApiError(403, "Forbidden")
            return view(*args, **kwargs)

        return wrapper

    return decorator


def error_response(err):
    return jsonify({"message": err.message, **err.extra}), err.status
