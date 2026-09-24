"""
Vercel Cron handler → /api/contests/sync

Vercel Cron Jobs hit `path` in vercel.json directly as a serverless function.
They do NOT pass through the `rewrites` rules, so /api/contests/sync needs
a real Python file here.

We simply re-export the Flask WSGI app (same as api/index.py).
Vercel's Python runtime will call it with PATH_INFO=/api/contests/sync,
which Flask routes to the sync_contests() view function.
"""

from app import app
