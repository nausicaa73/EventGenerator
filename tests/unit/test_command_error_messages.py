import pytest


def test_error_handler_does_not_show_python_exception_names(project):
    discord = pytest.importorskip("discord")
    from discord.ext import commands
    from event_engine.bot import EventBot

    bot = EventBot(project)

    class Context:
        message = type("Message", (), {"content": "*event bonbon"})()
        sent = []
        async def send(self, content=None, **kwargs):
            self.sent.append(content)

    ctx = Context()
    error = commands.CommandInvokeError(RuntimeError("secret traceback detail"))
    import asyncio
    asyncio.run(bot.on_command_error(ctx, error))
    assert ctx.sent
    assert "CommandInvokeError" not in ctx.sent[0]
    assert "RuntimeError" not in ctx.sent[0]
    assert "erreur interne" in ctx.sent[0].casefold()
