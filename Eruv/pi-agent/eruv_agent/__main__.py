"""Entry point: ``python -m eruv_agent --config /etc/eruv-agent/agent.yaml``.

Logs go to stderr only; under systemd they land in journald (no log files on
the SD card)."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from eruv_agent.agent import Agent
from eruv_agent.config import ConfigError, load_config

DEFAULT_CONFIG = "/etc/eruv-agent/agent.yaml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eruv_agent", description="Eruv OTDR monitoring agent")
    parser.add_argument("--config", default=DEFAULT_CONFIG, help=f"YAML config (default {DEFAULT_CONFIG})")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        stream=sys.stderr,
        level=args.log_level.upper(),
        format="%(levelname)s %(name)s: %(message)s",  # journald adds the timestamp
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        logging.getLogger("eruv_agent").critical("config error: %s", exc)
        return 2

    async def serve() -> None:
        agent = Agent(cfg)
        try:
            await agent.run()
        finally:
            await agent.aclose()

    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        return 0
    return 1  # run() only returns by raising; reaching here means a task stopped


if __name__ == "__main__":
    sys.exit(main())
