from __future__ import annotations

from pathlib import Path

from .api import create_app as create_base_app
from .chat_api import register_chat_routes
from .config import AVOConfig


def create_app(config_path: str = "avo.json"):
    config_file = Path(config_path).expanduser().resolve()
    config = AVOConfig.load(config_file)
    app = create_base_app(config_path)

    # The base app ends with a GET catch-all for the Expo SPA. Temporarily remove it so
    # /api/chat/* is registered ahead of that catch-all, then restore it as the final route.
    frontend_routes = [
        route for route in app.router.routes if getattr(route, "path", None) == "/{path:path}"
    ]
    if frontend_routes:
        app.router.routes = [route for route in app.router.routes if route not in frontend_routes]

    register_chat_routes(app, config=config, config_file=config_file)
    app.router.routes.extend(frontend_routes)
    return app
