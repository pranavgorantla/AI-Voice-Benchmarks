"""
pytest configuration for the voice-eval-harness test suite.

Sets DATABASE_URL to an in-memory SQLite DB so that tests never require
psycopg2 or a running PostgreSQL instance, even when the monorepo's
DATABASE_URL env var points at Postgres.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
