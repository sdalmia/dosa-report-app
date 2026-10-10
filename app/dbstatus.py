"""Whether the configured database will still be there after a deploy.

The response is safe to show publicly: dialect name and a yes/no, never the URL.
"""

import os

from app.extensions import db


def database_health():
    dialect = db.engine.dialect.name
    render = str(os.environ.get("RENDER", "")).strip()
    flask_env = str(os.environ.get("FLASK_ENV", "")).strip().casefold()
    hosted = bool(render) or flask_env == "production"
    # Render's disk is wiped on deploy, so the sqlite:///app.db fallback is not a store.
    persistent = not (dialect == "sqlite" and hosted)
    return {"dialect": dialect, "persistent": persistent}
