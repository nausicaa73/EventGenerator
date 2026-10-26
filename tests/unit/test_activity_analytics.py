import json

from event_engine.activity_manager import ActivityManager
from event_engine.database import connect


def setup_activity_database(manager):
    manager.start_event(123, "test")
    manager.join_player(123, "test", 101)
    manager.join_player(123, "test", 202)
    activity_manager = ActivityManager(manager)
    database_path = activity_manager._get_database(123, "test")
    with connect(database_path) as connection:
        entries = [
            (101, "bonbon", "command_claimed", {"outcome": "win", "rewards": {"currency": 5, "points": 2}}),
            (202, "bonbon", "command_claimed", {"outcome": "loss", "rewards": {"currency": -2, "points": 0}}),
            (101, "bonbon", "command_claimed", {"outcome": "zero", "rewards": {"currency": 0, "points": 1}}),
        ]
        connection.executemany(
            "INSERT INTO activity_history (user_id, activity_id, event_type, details) VALUES (?, ?, ?, ?)",
            [(uid, aid, event_type, json.dumps(details)) for uid, aid, event_type, details in entries],
        )
    return activity_manager


def test_luck_stats_include_losses_and_zero_outcomes(manager):
    activities = setup_activity_database(manager)
    stats = activities.get_command_luck_stats(123, "test", "bonbon", 101)
    assert stats["uses"] == 2
    assert stats["net_gain"] == 5
    assert stats["average"] == 2.5
    assert stats["server_uses"] == 3
    assert stats["server_net_gain"] == 3
    assert stats["server_average"] == 1


def test_points_evolution_is_per_player(manager):
    activities = setup_activity_database(manager)
    evolution = activities.get_points_evolution(123, "test")
    assert evolution[101] == [2, 3]
    assert evolution[202] == [0]


def test_evolution_uses_recorded_balances_for_points_and_currency(manager):
    manager.start_event(123, "test")
    manager.join_player(123, "test", 101)
    activities = ActivityManager(manager)
    database_path = activities._get_database(123, "test")
    with connect(database_path) as connection:
        connection.executemany(
            "INSERT INTO activity_history (user_id, activity_id, event_type, details) VALUES (?, ?, ?, ?)",
            [
                (101, "bonbon", "command_claimed", json.dumps({"rewards": {"currency": 6, "points": 0}, "balances": {"currency": 6, "points": 0}})),
                (101, "bonbon", "command_claimed", json.dumps({"rewards": {"currency": -2, "points": 0}, "balances": {"currency": 4, "points": 0}})),
                (101, "quiz", "activity_completed", json.dumps({"points": 3, "currency": 1})),
            ],
        )

    assert activities.get_evolution(123, "test", "currency")[101] == [6, 4, 5]
    assert activities.get_evolution(123, "test", "points")[101] == [0, 0, 3]
