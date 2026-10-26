from types import SimpleNamespace
import pytest


class FakeContext:
    def __init__(self, guild_id, author_id=10):
        self.guild = SimpleNamespace(id=guild_id)
        self.user_id = author_id
        self.author = SimpleNamespace(
            id=author_id,
            bot=False,
            name=f"User{author_id}",
            display_name=f"User{author_id}",
            mention=f"<@{author_id}>",
            display_avatar=SimpleNamespace(url="https://example.com/avatar.png"),
)
        self.message = SimpleNamespace(content="test")
        self.sent = []
        self.bot = SimpleNamespace(get_user=lambda _id: None, fetch_user=self.fetch_user)
        self.guild.get_member = lambda user_id: SimpleNamespace(
            id=user_id, display_name=f"Joueur{user_id}", name=f"Joueur{user_id}",
            display_avatar=SimpleNamespace(url="https://example.invalid/avatar.png"),
            mention=f"<@{user_id}>",
        )
    async def fetch_user(self, user_id):
        return self.guild.get_member(user_id)
    async def send(self, content=None, **kwargs):
        self.sent.append(content or kwargs)


def test_join_profile_and_ranking_commands(project):
    pytest.importorskip("discord")
    import asyncio
    from event_engine.bot import EventBot, EventCommands
    bot = EventBot(project)
    cog = EventCommands(bot.manager)
    ctx = FakeContext(701, 10)
    bot.manager.start_event(701, "test")

    asyncio.run(EventCommands.event_join.callback(cog, ctx, "test"))
    assert "rejoint" in ctx.sent[-1]
    asyncio.run(EventCommands.event_profile.callback(cog, ctx, None, None))
    assert "embed" in ctx.sent[-1]

    from event_engine.database import connect
    db = bot.manager.get_active_instance_database(701, "test")
    with connect(db) as connection:
        connection.execute("UPDATE players SET points=2, currency=15 WHERE user_id=10")
        connection.execute("INSERT INTO players(user_id, points, currency) VALUES (11, 9, 1)")
    asyncio.run(EventCommands.event_ranking.callback(cog, ctx, "test", "bonbons"))
    embed = ctx.sent[-1]["embed"]
    assert "bonbons" in embed.title.casefold()
    assert embed.fields[0].name.endswith("Joueur10")


def test_catalogue_and_info_commands(project):
    pytest.importorskip("discord")
    import asyncio
    from event_engine.bot import EventBot, EventCommands
    bot = EventBot(project)
    cog = EventCommands(bot.manager)
    ctx = FakeContext(702)
    asyncio.run(EventCommands.event_list.callback(cog, ctx))
    assert "embed" in ctx.sent[-1]
    asyncio.run(EventCommands.event_info.callback(cog, ctx, "test"))
    assert "embed" in ctx.sent[-1]
