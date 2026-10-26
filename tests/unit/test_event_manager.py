from datetime import date

from event_engine.database import connect


def test_ranking_can_sort_by_currency_and_break_ties(manager):
    manager.start_event(100, "test")
    database = manager.get_active_instance_database(100, "test")
    with connect(database) as connection:
        connection.executemany(
            "INSERT INTO players(user_id, points, currency) VALUES (?, ?, ?)",
            [(11, 10, 2), (12, 10, 9), (13, 4, 20)],
        )

    assert [r["user_id"] for r in manager.get_ranking(100, "test", sort_by="currency")] == [13, 12, 11]
    # Les points restent le critère principal ; la monnaie départage les égalités.
    assert [r["user_id"] for r in manager.get_ranking(100, "test", sort_by="points")] == [12, 11, 13]


def test_manual_stop_sets_finished_status_and_end_timestamp(manager):
    manager.start_event(100, "test")
    assert manager.stop_event(100, "test") is True
    with connect(manager.registry_path) as connection:
        row = connection.execute(
            "SELECT status, ended_at FROM event_instances WHERE guild_id=? AND event_id=?",
            ("100", "test"),
        ).fetchone()
    assert row["status"] == "finished"
    assert row["ended_at"]
    assert manager.stop_event(100, "test") is False


def test_expired_event_is_finished_and_timestamped(manager):
    manager.start_event(100, "test")
    manager.events["test"]["end_date"] = "2000-01-01"
    assert manager.get_active_event_ids(100) == []
    with connect(manager.registry_path) as connection:
        row = connection.execute(
            "SELECT status, ended_at FROM event_instances WHERE guild_id=? AND event_id=?",
            ("100", "test"),
        ).fetchone()
    assert row["status"] == "finished"
    assert row["ended_at"]


def test_start_rejects_expired_event_without_creating_database(manager):
    manager.events["test"]["end_date"] = "2000-01-01"
    try:
        manager.start_event(100, "test")
    except ValueError as error:
        assert "terminée" in str(error).casefold()
    else:
        raise AssertionError("Un événement expiré ne devrait pas démarrer")
