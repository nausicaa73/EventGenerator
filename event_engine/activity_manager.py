import json
import re
import time
import unicodedata
from datetime import datetime
from pathlib import Path

from event_engine.database import connect


ACTIVITY_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


class ActivityManager:
    def __init__(self, event_manager):
        self.manager = event_manager

    def get_activities(self, event_id: str) -> list[dict]:
        if event_id not in self.manager.events:
            raise ValueError(f"Événement inconnu : {event_id}")

        path = self.manager._safe_path(
            f"events/{event_id}/activities.json"
        )

        if not path.is_file():
            return []

        try:
            with path.open(encoding="utf-8") as file:
                data = json.load(file)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"Le fichier d'activités de l'événement "
                f"`{event_id}` est vide ou invalide."
            ) from error

        activities = data.get("activities")

        if not isinstance(activities, list):
            raise ValueError(
                f"Le fichier {path} doit contenir une liste activities."
            )

        seen_ids = set()

        for activity in activities:
            if not isinstance(activity, dict):
                raise ValueError(f"Activité invalide dans {path}")

            activity_id = activity.get("id")

            if (
                not isinstance(activity_id, str)
                or not ACTIVITY_ID_PATTERN.fullmatch(activity_id)
                or activity_id in seen_ids
            ):
                raise ValueError(
                    f"Identifiant invalide ou dupliqué dans {path} : "
                    f"{activity_id}"
                )

            seen_ids.add(activity_id)

            if activity.get("type") not in (
                "quiz", "riddle", "command"
            ):
                raise ValueError(
                    f"Type d'activité inconnu : {activity_id}"
                )

            if not isinstance(activity.get("name"), str):
                raise ValueError(
                    f"Nom manquant pour l'activité {activity_id}"
                )

            rewards = activity.get("rewards", {})

            if not isinstance(rewards, dict):
                raise ValueError(
                    f"Récompenses invalides pour {activity_id}"
                )

            for key in ("points", "currency"):
                value = rewards.get(key, 0)

                if type(value) is not int or value < 0:
                    raise ValueError(
                        f"Récompense {key} invalide pour {activity_id}"
                    )

            if activity.get("type") in ("quiz", "riddle"):
                answers = activity.get("answers")

                if (
                    not isinstance(answers, list)
                    or not answers
                    or not all(
                        isinstance(answer, str) and answer.strip()
                        for answer in answers
                    )
                ):
                    raise ValueError(
                        f"Réponses manquantes pour {activity_id}"
                    )

            if activity.get("type") == "command":
                cooldown = activity.get("cooldown_seconds", 86400)

                if type(cooldown) is not int or cooldown < 0:
                    raise ValueError(
                        f"Cooldown invalide pour {activity_id}"
                    )

        return [
            activity
            for activity in activities
            if activity.get("enabled", True)
        ]

    def get_activity(
        self,
        event_id: str,
        activity_id: str,
    ) -> dict | None:
        return next(
            (
                activity
                for activity in self.get_activities(event_id)
                if activity["id"] == activity_id
            ),
            None,
        )

    def _get_database(self, guild_id: int, event_id: str) -> Path:
        database_path = self.manager.get_active_instance_database(
            guild_id,
            event_id,
        )

        with connect(database_path) as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS activity_state (
                    user_id INTEGER NOT NULL,
                    activity_id TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    completed_at TEXT,
                    last_claimed_at INTEGER,
                    PRIMARY KEY (user_id, activity_id),
                    FOREIGN KEY (user_id)
                        REFERENCES players(user_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS activity_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    activity_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    details TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY (user_id)
                        REFERENCES players(user_id)
                        ON DELETE CASCADE
                );
            """)

        return database_path

    @staticmethod
    def _normalize_answer(answer: str) -> str:
        answer = unicodedata.normalize("NFKC", answer).casefold().strip()
        answer = re.sub(r"[^\w\s]", " ", answer, flags=re.UNICODE)
        return " ".join(answer.split())

    @staticmethod
    def _reward(
        connection,
        user_id: int,
        activity: dict,
        activity_id: str,
        event_type: str,
    ) -> None:
        rewards = activity.get("rewards", {})
        points = rewards.get("points", 0)
        currency = rewards.get("currency", 0)

        connection.execute(
            """
            UPDATE players
            SET points = points + ?,
                currency = currency + ?
            WHERE user_id = ?
            """,
            (points, currency, user_id),
        )

        connection.execute(
            """
            INSERT INTO activity_history
                (user_id, activity_id, event_type, details)
            VALUES (?, ?, ?, ?)
            """,
            (
                user_id,
                activity_id,
                event_type,
                json.dumps(
                    {"points": points, "currency": currency},
                    ensure_ascii=False,
                ),
            ),
        )

    def answer(
        self,
        guild_id: int,
        event_id: str,
        user_id: int,
        activity_id: str,
        answer: str,
    ) -> dict:
        activity = self.get_activity(event_id, activity_id)

        if activity is None:
            raise ValueError("Cette activité n'existe pas ou est désactivée.")

        if activity["type"] not in ("quiz", "riddle"):
            raise ValueError(
                "Cette activité ne se réalise pas avec une réponse."
            )

        database_path = self._get_database(guild_id, event_id)
        now = int(time.time())
        now_text = datetime.now().astimezone().isoformat()

        with connect(database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")

            player = connection.execute(
                "SELECT 1 FROM players WHERE user_id = ?",
                (user_id,),
            ).fetchone()

            if player is None:
                return {"status": "not_joined"}

            connection.execute(
                """
                INSERT OR IGNORE INTO activity_state
                    (user_id, activity_id)
                VALUES (?, ?)
                """,
                (user_id, activity_id),
            )

            state = connection.execute(
                """
                SELECT attempts, completed_at, last_claimed_at
                FROM activity_state
                WHERE user_id = ? AND activity_id = ?
                """,
                (user_id, activity_id),
            ).fetchone()

            repeatable = activity.get("repeatable", False)

            if state["completed_at"] and not repeatable:
                return {"status": "completed"}

            if repeatable and state["last_claimed_at"] is not None:
                cooldown = activity.get("cooldown_seconds", 0)
                remaining = cooldown - (now - state["last_claimed_at"])

                if remaining > 0:
                    return {
                        "status": "cooldown",
                        "remaining": remaining,
                    }

            max_attempts = activity.get("max_attempts")
            attempts = state["attempts"]

            if max_attempts is not None and attempts >= max_attempts:
                return {"status": "exhausted"}

            attempts += 1

            accepted_answers = {
                self._normalize_answer(value)
                for value in activity["answers"]
            }

            is_correct = (
                self._normalize_answer(answer) in accepted_answers
            )

            if not is_correct:
                connection.execute(
                    """
                    UPDATE activity_state
                    SET attempts = ?
                    WHERE user_id = ? AND activity_id = ?
                    """,
                    (attempts, user_id, activity_id),
                )

                connection.execute(
                    """
                    INSERT INTO activity_history
                        (user_id, activity_id, event_type, details)
                    VALUES (?, ?, 'answer_wrong', ?)
                    """,
                    (
                        user_id,
                        activity_id,
                        json.dumps({"attempt": attempts}),
                    ),
                )

                return {
                    "status": "wrong",
                    "attempts": attempts,
                    "max_attempts": max_attempts,
                }

            connection.execute(
                """
                UPDATE activity_state
                SET attempts = ?,
                    completed_at = ?,
                    last_claimed_at = ?
                WHERE user_id = ? AND activity_id = ?
                """,
                (
                    attempts,
                    now_text,
                    now,
                    user_id,
                    activity_id,
                ),
            )

            self._reward(
                connection,
                user_id,
                activity,
                activity_id,
                "activity_completed",
            )

        return {
            "status": "correct",
            "rewards": activity.get("rewards", {}),
        }

    def claim_command(
        self,
        guild_id: int,
        event_id: str,
        user_id: int,
        activity_id: str,
    ) -> dict:
        activity = self.get_activity(event_id, activity_id)

        if activity is None:
            raise ValueError("Cette activité n'existe pas ou est désactivée.")

        if activity["type"] != "command":
            raise ValueError(
                "Cette activité ne peut pas être lancée avec cette commande."
            )

        database_path = self._get_database(guild_id, event_id)
        now = int(time.time())
        now_text = datetime.now().astimezone().isoformat()

        with connect(database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")

            player = connection.execute(
                "SELECT 1 FROM players WHERE user_id = ?",
                (user_id,),
            ).fetchone()

            if player is None:
                return {"status": "not_joined"}

            connection.execute(
                """
                INSERT OR IGNORE INTO activity_state
                    (user_id, activity_id)
                VALUES (?, ?)
                """,
                (user_id, activity_id),
            )

            state = connection.execute(
                """
                SELECT completed_at, last_claimed_at
                FROM activity_state
                WHERE user_id = ? AND activity_id = ?
                """,
                (user_id, activity_id),
            ).fetchone()

            repeatable = activity.get("repeatable", True)

            if state["completed_at"] and not repeatable:
                return {"status": "completed"}

            cooldown = activity.get("cooldown_seconds", 86400)
            last_claimed = state["last_claimed_at"]

            if last_claimed is not None:
                remaining = cooldown - (now - last_claimed)

                if remaining > 0:
                    return {
                        "status": "cooldown",
                        "remaining": remaining,
                    }

            connection.execute(
                """
                UPDATE activity_state
                SET last_claimed_at = ?,
                    completed_at = CASE
                        WHEN ? THEN ?
                        ELSE completed_at
                    END
                WHERE user_id = ? AND activity_id = ?
                """,
                (
                    now,
                    int(not repeatable),
                    now_text,
                    user_id,
                    activity_id,
                ),
            )

            self._reward(
                connection,
                user_id,
                activity,
                activity_id,
                "command_claimed",
            )

        return {
            "status": "success",
            "rewards": activity.get("rewards", {}),
        }