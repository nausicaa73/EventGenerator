from types import SimpleNamespace
import pytest


def make_context(guild_id, user_id=20):
    member = SimpleNamespace(
        id=user_id, display_name=f"Joueur{user_id}", name=f"Joueur{user_id}",
        mention=f"<@{user_id}>",
        display_avatar=SimpleNamespace(url="https://example.invalid/avatar.png"),
    )
    guild = SimpleNamespace(id=guild_id, get_member=lambda _id: member)
    return SimpleNamespace(
        guild=guild, author=member, message=SimpleNamespace(content="test"), sent=[],
        send=None,
    )


def attach_send(ctx):
    async def send(content=None, **kwargs):
        ctx.sent.append(content or kwargs)
    ctx.send = send
    return ctx


def test_activities_activity_answer_do_and_direct_shortcut(project):
    pytest.importorskip("discord")
    import asyncio
    from event_engine.bot import EventBot, EventCommands
    bot = EventBot(project)
    cog = EventCommands(bot.manager)
    ctx = attach_send(make_context(703))
    bot.manager.start_event(703, "test")
    bot.manager.join_player(703, "test", 20)

    asyncio.run(EventCommands.event_activities.callback(cog, ctx, "test"))
    assert "embed" in ctx.sent[-1]
    asyncio.run(EventCommands.event_activity.callback(cog, ctx, "bonbon", "test"))
    assert "embed" in ctx.sent[-1]

    asyncio.run(EventCommands.event_answer.callback(cog, ctx, "quiz", "bleu", rest=""))
    assert "Bonne réponse" in ctx.sent[-1]

    asyncio.run(EventCommands.event_do.callback(cog, ctx, "bonbon", "test"))
    assert "Récompense test" in ctx.sent[-1]

    # La syntaxe courte *event bonbon délègue au même exécuteur.
    calls = []
    async def runner(_ctx, activity_id, event_id=None):
        calls.append((activity_id, event_id))
    cog.run_command_activity = runner
    asyncio.run(EventCommands.event.callback(cog, ctx, "bonbon", "test"))
    assert calls == [("bonbon", "test")]
