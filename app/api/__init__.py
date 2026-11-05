from .accounts import bp as accounts_bp
from .content import bp as content_bp
from .store import bp as store_bp


def register_api(app):
    for blueprint in (accounts_bp, content_bp, store_bp):
        app.register_blueprint(blueprint, url_prefix="/api/v1")
