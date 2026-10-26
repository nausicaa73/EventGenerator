import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from event_engine.outcome_engine import execute_outcome

from event_engine.database import (
    initialize_instance_database,
    initialize_registry,
    connect,
)


EVENT_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


class EventManager:
    def __init__(self, project_dir: Path):
        self.project_dir = project_dir.resolve()

        self.settings = self._read_json("config/settings.json")

        self.events_dir = self._safe_path(
            self.settings["events_directory"]
        )
        self.database_dir = self._safe_path(
            self.settings["database_directory"]
        )
        self.registry_path = self._safe_path(
            self.settings["registry_database"]
        )

        self.events = {}
        self._load_events()

        initialize_registry(self.registry_path)
        self._ensure_registry_migrations()

    def _ensure_registry_migrations(self) -> None:
        """Ajoute les colonnes de suivi manquantes sans toucher aux données existantes."""
        with connect(self.registry_path) as connection:
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(event_instances)")
            }
            if "ended_at" not in columns:
                connection.execute(
                    "ALTER TABLE event_instances ADD COLUMN ended_at TEXT"
                )
            # Les anciennes instances déjà terminées n'ont pas de date d'arrêt
            # historisée. On les marque à la date de migration plutôt que de les
            # laisser avec un champ vide ; les nouveaux arrêts enregistrent l'heure exacte.
            connection.execute(
                """UPDATE event_instances
                   SET ended_at = CURRENT_TIMESTAMP
                   WHERE status = 'finished' AND ended_at IS NULL"""
            )

    def _safe_path(self, relative_path: str) -> Path:
        path = (self.project_dir / relative_path).resolve()

        if not path.is_relative_to(self.project_dir):
            raise ValueError(f"Chemin hors du projet interdit : {path}")

        return path

    def _read_json(self, relative_path: str) -> dict:
        path = self._safe_path(relative_path)

        with path.open(encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, dict):
            raise ValueError(f"Objet JSON attendu dans {path}")

        return data

    def _load_events(self) -> None:
        if not self.events_dir.is_dir():
            raise FileNotFoundError(
                f"Dossier des événements absent : {self.events_dir}"
            )

        for directory in sorted(self.events_dir.iterdir()):
            if not directory.is_dir():
                continue

            config_path = directory / "event.json"

            if not config_path.is_file():
                continue

            with config_path.open(encoding="utf-8") as file:
                event = json.load(file)

            event_id = event.get("id")

            if (
                not isinstance(event_id, str)
                or not EVENT_ID_PATTERN.fullmatch(event_id)
                or event_id != directory.name
            ):
                raise ValueError(
                    f"Identifiant invalide ou différent du dossier : "
                    f"{config_path}"
                )

            if event_id in self.events:
                raise ValueError(f"Identifiant d'événement dupliqué : {event_id}")

            if not event.get("name") or not event.get("description"):
                raise ValueError(
                    f"Le nom et la description sont obligatoires : {config_path}"
                )

            self.events[event_id] = event

    def list_events(self) -> list[dict]:
        # Pour le moment, tous les événements activés sont visibles.
        # La visibilité publique/privée sera ajoutée ultérieurement.
        return [
            event
            for event in self.events.values()
            if event.get("enabled", True)
        ]

    def get_event(self, event_id: str) -> dict | None:
        return self.events.get(event_id)

    def _event_has_ended(self, event_id: str) -> bool:
        """Vrai si la date de fin de l'événement est dépassée.

        Une date seule (AAAA-MM-JJ) inclut toute la journée indiquée.
        Une date avec heure est comparée précisément.
        """
        event = self.get_event(event_id)
        if not event or not event.get("end_date"):
            return False

        value = event["end_date"]
        try:
            end = datetime.fromisoformat(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Date invalide dans l'événement : end_date") from exc

        if len(value) == 10:
            from datetime import date
            return date.today() > end.date()

        from datetime import timezone
        now = datetime.now(timezone.utc) if end.tzinfo else datetime.now()
        if end.tzinfo:
            end = end.astimezone(timezone.utc)
        return now > end

    def _mark_expired_instances(self, guild_id: int | None = None) -> None:
        """Passe automatiquement les instances dépassées à l'état finished."""
        query = "SELECT id, guild_id, event_id FROM event_instances WHERE status = 'active'"
        params = ()
        if guild_id is not None:
            query += " AND guild_id = ?"
            params = (str(guild_id),)
        with connect(self.registry_path) as connection:
            rows = connection.execute(query, params).fetchall()
            expired_ids = []
            for row in rows:
                try:
                    expired = self._event_has_ended(row["event_id"])
                except ValueError:
                    expired = False
                if expired:
                    expired_ids.append(row["id"])
            if expired_ids:
                connection.executemany(
                    """UPDATE event_instances
                       SET status = 'finished',
                           ended_at = COALESCE(ended_at, CURRENT_TIMESTAMP)
                       WHERE id = ?""",
                    [(instance_id,) for instance_id in expired_ids],
                )

    def stop_event(self, guild_id: int, event_id: str) -> bool:
        """Arrête une instance active sans supprimer ses données."""
        with connect(self.registry_path) as connection:
            cursor = connection.execute(
                """UPDATE event_instances
                   SET status = 'finished', ended_at = CURRENT_TIMESTAMP
                   WHERE guild_id = ? AND event_id = ? AND status = 'active'""",
                (str(guild_id), event_id),
            )
        return cursor.rowcount > 0

    def start_event(self, guild_id: int, event_id: str) -> Path:
        event = self.get_event(event_id)

        if event is None:
            raise ValueError(f"Événement inconnu : {event_id}")

        if not event.get("enabled", True):
            raise ValueError("Cet événement est désactivé.")

        start_value = event.get("start_date")
        if start_value:
            try:
                start = datetime.fromisoformat(start_value)
            except (TypeError, ValueError) as exc:
                raise ValueError("Date invalide dans l'événement : start_date") from exc
            from datetime import timezone
            now = datetime.now(timezone.utc) if start.tzinfo else datetime.now()
            if start.tzinfo:
                start = start.astimezone(timezone.utc)
            if now < start:
                raise ValueError("Cet événement n'est pas encore disponible.")

        if self._event_has_ended(event_id):
            raise ValueError("La période de cet événement est terminée.")

        guild_text = str(guild_id)
        database_path = self.database_dir / f"{guild_text}_{event_id}.db"

        with connect(self.registry_path) as connection:
            existing = connection.execute(
                """
                SELECT id, database_path
                FROM event_instances
                WHERE guild_id = ? AND event_id = ? AND status = 'active'
                """,
                (guild_text, event_id),
            ).fetchone()

            if existing:
                raise ValueError(
                    "Cet événement est déjà actif sur ce serveur."
                )

            if database_path.exists():
                raise FileExistsError(
                    f"La base existe déjà : {database_path.name}. "
                    "Par sécurité, elle ne sera pas écrasée."
                )

            initialize_instance_database(database_path)

            try:
                connection.execute(
                    """
                    INSERT INTO event_instances
                        (guild_id, event_id, database_path)
                    VALUES (?, ?, ?)
                    """,
                    (
                        guild_text,
                        event_id,
                        str(database_path.relative_to(self.project_dir)),
                    ),
                )
            except Exception:
                database_path.unlink(missing_ok=True)
                raise

        return database_path

    def get_active_instance_database(
        self,
        guild_id: int,
        event_id: str,
    ) -> Path:
        """Retourne la base de données de l'événement actif sur ce serveur."""

        event = self.get_event(event_id)

        if event is None or not event.get("enabled", True):
            raise ValueError(
                f"Événement inconnu ou désactivé : {event_id}"
            )

        if self._event_has_ended(event_id):
            self.stop_event(guild_id, event_id)
            raise ValueError("Cet événement est terminé : sa date de fin est dépassée.")

        self._mark_expired_instances(guild_id)
        with connect(self.registry_path) as connection:
            instance = connection.execute(
                """
                SELECT database_path
                FROM event_instances
                WHERE guild_id = ?
                  AND event_id = ?
                  AND status = 'active'
                """,
                (str(guild_id), event_id),
            ).fetchone()

        if instance is None:
            raise ValueError(
                "Cet événement n'a pas été lancé sur ce serveur."
            )

        database_path = self._safe_path(instance["database_path"])

        if not database_path.is_file():
            raise FileNotFoundError(
                "La base de données de cet événement est introuvable."
            )

        return database_path

    def join_player(
        self,
        guild_id: int,
        event_id: str,
        user_id: int,
    ) -> bool:
        """Inscrit un joueur. Retourne False s'il est déjà inscrit."""

        database_path = self.get_active_instance_database(
            guild_id,
            event_id,
        )

        with connect(database_path) as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO players (user_id)
                VALUES (?)
                """,
                (user_id,),
            )

        return cursor.rowcount == 1

    def get_player_profile(
        self,
        guild_id: int,
        event_id: str,
        user_id: int,
    ):
        """Retourne le profil du joueur, ou None s'il n'est pas inscrit."""

        database_path = self.get_active_instance_database(
            guild_id,
            event_id,
        )

        with connect(database_path) as connection:
            return connection.execute(
                """
                SELECT user_id, joined_at, points, currency
                FROM players
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()

    def get_ranking(
        self,
        guild_id: int,
        event_id: str,
        limit: int = 10,
        sort_by: str = "points",
    ) -> list:
        """Retourne le classement par points ou par monnaie."""
        if sort_by not in ("points", "currency"):
            raise ValueError("Le classement doit être trié par 'points' ou 'currency'.")

        database_path = self.get_active_instance_database(guild_id, event_id)
        # La métrique choisie est prioritaire ; l'autre sert de départage.
        # Les colonnes proviennent d'une liste blanche, jamais d'une entrée SQL libre.
        secondary = "currency" if sort_by == "points" else "points"
        with connect(database_path) as connection:
            return connection.execute(
                f"""SELECT user_id, points, currency
                    FROM players
                    ORDER BY {sort_by} DESC, {secondary} DESC,
                             joined_at ASC, user_id ASC
                    LIMIT ?""",
                (limit,),
            ).fetchall()

    def get_active_event_ids(self, guild_id: int) -> list[str]:
        """Liste les événements actifs sur un serveur."""
        self._mark_expired_instances(guild_id)

        with connect(self.registry_path) as connection:
            rows = connection.execute(
                """
                SELECT event_id
                FROM event_instances
                WHERE guild_id = ? AND status = 'active'
                ORDER BY event_id
                """,
                (str(guild_id),),
            ).fetchall()

        return [
            row["event_id"]
            for row in rows
            if (
                self.get_event(row["event_id"]) is not None
                and self.get_event(row["event_id"]).get("enabled", True)
            )
        ]

    def get_joined_event_ids(
        self,
        guild_id: int,
        user_id: int,
    ) -> list[str]:
        """Liste les événements actifs auxquels le joueur est inscrit."""
        self._mark_expired_instances(guild_id)

        with connect(self.registry_path) as connection:
            instances = connection.execute(
                """
                SELECT event_id, database_path
                FROM event_instances
                WHERE guild_id = ? AND status = 'active'
                ORDER BY event_id
                """,
                (str(guild_id),),
            ).fetchall()

        joined_events = []

        for instance in instances:
            event = self.get_event(instance["event_id"])

            if event is None or not event.get("enabled", True):
                continue

            database_path = self._safe_path(instance["database_path"])

            if not database_path.is_file():
                continue

            with connect(database_path) as connection:
                player = connection.execute(
                    "SELECT 1 FROM players WHERE user_id = ?",
                    (user_id,),
                ).fetchone()

            if player is not None:
                joined_events.append(instance["event_id"])

        return joined_events
    