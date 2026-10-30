"""
PACKAGE: app.core - shared plumbing every other package relies on.

    config.py       settings from .env
    logging.py      log format
    database.py     SQLite/Postgres connection
    vectorstore.py  Qdrant connection
    access.py       THE access rules: can_read(user, resource)
"""
