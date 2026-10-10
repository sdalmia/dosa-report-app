"""Production must not run at DEBUG. OAuth libraries print tokens at DEBUG."""

import logging
import os
import tempfile
import unittest

_DB = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
os.environ["DATABASE_URL"] = "sqlite:///" + _DB.name
os.environ["SECRET_KEY"] = "test-secret"
os.environ.pop("FLASK_DEBUG", None)

from app import create_app
from app.config import Config


class ProductionLogTests(unittest.TestCase):
    def test_production_config_is_not_debug(self):
        self.assertFalse(Config.DEBUG)
        os.environ["OAUTHLIB_DEBUG"] = "1"
        app = create_app()
        self.assertFalse(app.debug)
        self.assertFalse(app.config["DEBUG"])
        self.assertGreaterEqual(logging.getLogger().getEffectiveLevel(), logging.INFO)
        self.assertGreaterEqual(app.logger.getEffectiveLevel(), logging.INFO)
        for name in ("requests_oauthlib", "oauthlib", "urllib3", "flask_dance", "asyncio"):
            self.assertGreaterEqual(logging.getLogger(name).getEffectiveLevel(), logging.INFO)
        self.assertNotIn("OAUTHLIB_DEBUG", os.environ)
