from types import SimpleNamespace
import pytest


def test_start_and_stop_commands_update_lifecycle(project):
    pytest.importorskip("discord")
    from event_engine.bot import EventBot, EventCommands
    bot = EventBot(project)
    cog = EventCommands(bot.manager)

    class Context:
        guild = SimpleNamespace(id=700)
        message = SimpleNamespace(content="*event start test")
        sent = []
        async def send(self, content=None, **kwargs):
            self.sent.append(content or kwargs)

    ctx = Context()
    import asyncio
    asyncio.run(EventCommands.event_start.callback(cog, ctx, "test"))
    assert "est lancé" in ctx.sent[-1]
    asyncio.run(EventCommands.event_stop.callback(cog, ctx, "test"))
    assert "est arrêté" in ctx.sent[-1]
    from event_engine.database import connect
    with connect(bot.manager.registry_path) as connection:
        row = connection.execute("SELECT status, ended_at FROM event_instances WHERE guild_id='700'").fetchone()
    assert row["status"] == "finished" and row["ended_at"]


def test_start_stop_commands_require_manage_server(project):
    pytest.importorskip("discord")
    from event_engine.bot import EventCommands
    for name in ("event_start", "event_stop"):
        command = getattr(EventCommands, name)
        assert command.checks, f"La commande {name} doit avoir une vérification de permission"
