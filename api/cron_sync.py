"""
Vercel Cron handler for /api/cron_sync → triggers contest sync.

Why this file exists:
  Vercel Cron Jobs call the `path` in vercel.json DIRECTLY as a serverless
  function — they do NOT go through `rewrites`. So /api/contests/sync would
  need a file at api/contests/sync.py, but Vercel's Python runtime only
  supports ONE level deep (api/*.py). Subdirectories are ignored.

  Solution: name this file api/cron_sync.py and point the cron `path` here.
  The Flask app handles the actual contest sync logic via the WSGI call.
"""

from app import app
