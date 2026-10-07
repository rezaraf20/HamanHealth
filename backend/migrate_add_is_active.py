"""
Migration: add is_active column to cough_sessions table.
Run once on the server:
  docker compose -f deploy/docker-compose.haman.yml exec haman-api python migrate_add_is_active.py
"""
import os
import sys

# Make sure we can find app modules when run from /app inside the container
sys.path.insert(0, "/app")

from sqlalchemy import text
from app.database import engine

with engine.connect() as conn:
    # Check if column already exists
    result = conn.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'cough_sessions' AND column_name = 'is_active'
    """))
    if result.fetchone():
        print("Column 'is_active' already exists — nothing to do.")
    else:
        conn.execute(text(
            "ALTER TABLE cough_sessions ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT FALSE"
        ))
        conn.commit()
        print("Added 'is_active' column to cough_sessions.")
