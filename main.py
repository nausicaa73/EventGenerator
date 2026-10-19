import json
import os
from pathlib import Path

from event_engine.bot import EventBot


PROJECT_DIR = Path(__file__).resolve().parent


def load_env():
    env_path = PROJECT_DIR / ".env"

    if not env_path.is_file():
        raise FileNotFoundError("Fichier .env introuvable.")

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        os.environ.setdefault(
            key.strip(),
            value.strip().strip('"').strip("'"),
        )


def main():
    load_env()

    token = os.getenv("DISCORD_TOKEN")

    if not token or token == "REMPLACE_PAR_LE_TOKEN_DU_BOT":
        raise RuntimeError("Configure DISCORD_TOKEN dans .env.")

    settings_path = PROJECT_DIR / "config/settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))

    bot = EventBot(PROJECT_DIR)
    bot.run(token)


if __name__ == "__main__":
    main()