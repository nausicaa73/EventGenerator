"""Contrats de commandes : syntaxe, permissions et délégation vers le gestionnaire."""
import pytest


def test_expected_commands_are_registered(project):
    pytest.importorskip("discord")
    from event_engine.bot import EventBot
    bot = EventBot(project)
    from event_engine.bot import EventCommands
    cog = EventCommands(bot.manager)
    expected = {"event", "list", "info", "start", "stop", "join", "profile",
                "ranking", "activities", "activity", "answer", "do"}
    commands_by_name = {
        command.name: command
        for command in cog.get_commands()
    }
    group = commands_by_name.get("event")
    assert group is not None, "La commande principale 'event' n'est pas enregistrée"
    registered = {command.name for command in group.commands}
    assert expected - {"event"} <= registered
    assert group.invoke_without_command is True


def test_direct_activity_syntax_delegates_to_activity_runner(project):
    pytest.importorskip("discord")
    from event_engine.bot import EventBot, EventCommands
    bot = EventBot(project)
    cog = EventCommands(bot.manager)
    calls = []
    async def runner(ctx, activity_id, event_id=None):
        calls.append((activity_id, event_id))
    cog.run_command_activity = runner
    # La commande de groupe sans sous-commande est le raccourci *event bonbon.
    import asyncio
    ctx = type("Context", (), {"send": lambda *a, **k: None})()
    asyncio.run(cog.event.callback(cog, ctx, "bonbon", None))
    assert calls == [("bonbon", None)]
