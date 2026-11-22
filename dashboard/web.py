"""Start and stop the dashboard inside the bot's event loop."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

log = logging.getLogger("socialize")


async def start_dashboard(bot: Any) -> None:
    try:
        import uvicorn
        from dashboard import create_app, oauth_configured
    except Exception:
        log.exception("Dashboard dependencies are missing; web UI will not start")
        return

    port = int(os.getenv("PORT", "8080"))
    app = create_app(bot)
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
        lifespan="off",
        access_log=False,
    )
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
    bot.dashboard_server = server

    async def _serve() -> None:
        try:
            await server.serve()
        except OSError:
            log.exception("Dashboard could not bind to port %s; the bot will keep running", port)

    bot.dashboard_task = asyncio.create_task(_serve())
    if oauth_configured():
        log.info("Dashboard listening on 0.0.0.0:%s", port)
    else:
        log.info(
            "Dashboard listening on 0.0.0.0:%s (login disabled — set DISCORD_CLIENT_SECRET to enable it)",
            port,
        )


async def stop_dashboard(bot: Any) -> None:
    server = getattr(bot, "dashboard_server", None)
    if server is not None:
        server.should_exit = True
    task = getattr(bot, "dashboard_task", None)
    if task is not None:
        try:
            await asyncio.wait_for(task, timeout=4)
        except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
            task.cancel()
