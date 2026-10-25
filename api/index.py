"""
Vercel serverless entry point.

Vercel looks for a WSGI/ASGI callable named `app` in this file. We import
the Flask app defined in the project root and expose it here. All routing
is handled by vercel.json, which sends every request to this function.
"""

import os
import sys

# Make the project root importable so we can `import app` (app.py).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402  (Flask WSGI app instance)

# Vercel's Python runtime will detect and serve this `app` callable.
