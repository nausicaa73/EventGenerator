"""Fixtures de tests. En projet réel, le module event_engine.database est utilisé.

Le fallback SQLite ne sert qu'à permettre de lancer les tests autonomément depuis
l'archive de patch, qui ne remplace volontairement pas le database.py du projet.
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
import types
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    database_spec = importlib.util.find_spec("event_engine.database")
except ModuleNotFoundError:
    database_spec = None

if database_spec is None:
    database = types.ModuleType("event_engine.database")

    def connect(path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize_registry(path):
        with connect(path) as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS event_instances (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    database_path TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active'
                        CHECK(status IN ('active', 'finished')),
                    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

    def initialize_instance_database(path):
        with connect(path) as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS players (
                    user_id INTEGER PRIMARY KEY,
                    joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    points INTEGER NOT NULL DEFAULT 0,
                    currency INTEGER NOT NULL DEFAULT 0
                )
            """)

    database.connect = connect
    database.initialize_registry = initialize_registry
    database.initialize_instance_database = initialize_instance_database
    sys.modules["event_engine.database"] = database


@pytest.fixture

def project(tmp_path):
    """Petit projet temporaire avec un événement test et une activité bonbon."""
    (tmp_path / "config").mkdir()
    (tmp_path / "events" / "test").mkdir(parents=True)
    (tmp_path / "database").mkdir()
    (tmp_path / "config" / "settings.json").write_text(
        '{"events_directory":"events","database_directory":"database",'
        '"registry_database":"database/engine.db","command_prefix":"*"}',
        encoding="utf-8",
    )
    (tmp_path / "events" / "test" / "event.json").write_text(
        '{"id":"test","name":"Événement de test",'
        '"description":"Événement pour les tests", "currency":"bonbons",'
        '"start_date":"2020-01-01", "end_date":"2099-12-31"}',
        encoding="utf-8",
    )
    (tmp_path / "events" / "test" / "activities.json").write_text(
        '{"activities":[{"id":"bonbon","name":"Bonbon","type":"command",'
        '"description":"activité test", "cooldown_seconds":0, "repeatable":true, "outcomes":[{'
        '"id":"success","probability":1,"rewards":[{"type":"points","values":[2]},'
        '{"type":"currency","values":[3]}], "messages":["Récompense test"]}]},'
        '{"id":"quiz","name":"Quiz test","type":"quiz","description":"Question test",'
        '"question":"Quelle couleur ?","answers":["bleu"],"rewards":{"points":1,"currency":1}}]}',
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture

def manager(project):
    from event_engine.event_manager import EventManager
    return EventManager(project)
