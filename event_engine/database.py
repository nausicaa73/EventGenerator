import sqlite3
from pathlib import Path


def connect(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_registry(database_path: Path) -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)

    with connect(database_path) as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS event_instances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                database_path TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'finished')),
                started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                finished_at TEXT
            );

            CREATE UNIQUE INDEX IF NOT EXISTS one_active_event_per_pair
            ON event_instances(guild_id, event_id)
            WHERE status = 'active';
        """)


def initialize_instance_database(database_path: Path) -> None:
    """Initialise une nouvelle base sans écraser un fichier existant."""
    database_path.parent.mkdir(parents=True, exist_ok=True)

    # Création exclusive : échoue si le fichier existe déjà.
    with database_path.open("xb"):
        pass

    try:
        with connect(database_path) as connection:
            connection.executescript("""
                CREATE TABLE players (
                    user_id INTEGER PRIMARY KEY,
                    joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    points INTEGER NOT NULL DEFAULT 0,
                    currency INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE activity_progress (
                    user_id INTEGER NOT NULL,
                    activity_id TEXT NOT NULL,
                    completed_at TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (user_id, activity_id),
                    FOREIGN KEY (user_id)
                        REFERENCES players(user_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE missions (
                    user_id INTEGER NOT NULL,
                    mission_id TEXT NOT NULL,
                    completed_at TEXT,
                    PRIMARY KEY (user_id, mission_id),
                    FOREIGN KEY (user_id)
                        REFERENCES players(user_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE inventory (
                    user_id INTEGER NOT NULL,
                    item_id TEXT NOT NULL,
                    quantity INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (user_id, item_id),
                    FOREIGN KEY (user_id)
                        REFERENCES players(user_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE reward_claims (
                    user_id INTEGER NOT NULL,
                    reward_id TEXT NOT NULL,
                    claimed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, reward_id),
                    FOREIGN KEY (user_id)
                        REFERENCES players(user_id)
                        ON DELETE CASCADE
                );
            """)
    except Exception:
        database_path.unlink(missing_ok=True)
        raise