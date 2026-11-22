"""Run the dashboard on its own (used for local HTTP checks)."""

from __future__ import annotations

import os

import uvicorn

from dashboard import create_app


def main() -> None:
    port = int(os.getenv("PORT", "8080"))
    app = create_app(bot=None)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
