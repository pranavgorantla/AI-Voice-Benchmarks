---
name: Voice Eval Harness DATABASE_URL isolation
description: The pnpm monorepo's DATABASE_URL env var points to PostgreSQL; harness scripts and tests must override it to SQLite.
---

# DATABASE_URL conflict between monorepo and harness

The monorepo sets `DATABASE_URL` in the environment pointing to a PostgreSQL instance (for the api-server artifact). When running harness Python scripts from bash, this env var is inherited and causes SQLAlchemy to try to load psycopg2, which is not installed.

**Fix for scripts:**
```bash
DATABASE_URL=sqlite:///./results.db python -m scripts.seed_sample_data
```

**Fix for tests:** `tests/conftest.py` sets `os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")` before any imports, so pytest always uses in-memory SQLite regardless of environment.

**Why:** Storage module creates the SQLAlchemy engine at import time (`engine = create_engine(settings.database_url, ...)`). There is no lazy initialization. The conftest approach is the cleanest solution that doesn't require restructuring the module.
