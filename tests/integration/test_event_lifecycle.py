"""Tests de flux de bout en bout sur SQLite temporaire, sans connexion Discord."""
from event_engine.database import connect


def test_start_join_activity_profile_ranking_stop_flow(manager):
    manager.start_event(200, "test")
    assert manager.join_player(200, "test", 501) is True
    assert manager.join_player(200, "test", 501) is False

    profile = manager.get_player_profile(200, "test", 501)
    assert profile["points"] == 0
    assert profile["currency"] == 0

    database = manager.get_active_instance_database(200, "test")
    with connect(database) as connection:
        connection.execute(
            "UPDATE players SET points=7, currency=13 WHERE user_id=501"
        )
    ranking = manager.get_ranking(200, "test", sort_by="currency")
    assert ranking[0]["user_id"] == 501
    assert ranking[0]["currency"] == 13

    assert manager.stop_event(200, "test") is True
    # L'arrêt conserve les données, mais bloque l'accès normal à l'instance active.
    with connect(manager.registry_path) as connection:
        row = connection.execute(
            "SELECT status, ended_at, database_path FROM event_instances WHERE guild_id=? AND event_id=?",
            ("200", "test"),
        ).fetchone()
    assert row["status"] == "finished" and row["ended_at"]
    assert (manager.project_dir / row["database_path"]).is_file()


def test_expiration_closes_instance_and_preserves_player_data(manager):
    manager.start_event(201, "test")
    manager.join_player(201, "test", 502)
    manager.events["test"]["end_date"] = "2000-01-01"
    assert manager.get_active_event_ids(201) == []
    with connect(manager.registry_path) as connection:
        row = connection.execute(
            "SELECT status, ended_at, database_path FROM event_instances WHERE guild_id=? AND event_id=?",
            ("201", "test"),
        ).fetchone()
    assert row["status"] == "finished" and row["ended_at"]
    with connect(manager.project_dir / row["database_path"]) as connection:
        assert connection.execute("SELECT user_id FROM players").fetchone()["user_id"] == 502
