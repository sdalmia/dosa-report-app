"""Gunicorn process model for the 512 MB instance.

Start command:

    gunicorn -c gunicorn.conf.py run:app

Two threaded workers match the 190–250 MB baseline. max_requests recycles a
worker that has kept a large parse. Render sets PORT.
"""

import os

bind = "0.0.0.0:" + os.environ.get("PORT", "8000")
workers = 2
worker_class = "gthread"
threads = 4
max_requests = 500
max_requests_jitter = 50
timeout = 120
loglevel = "info"
accesslog = "-"
errorlog = "-"
