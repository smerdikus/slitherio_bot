from __future__ import annotations

import argparse
import asyncio
import logging
from dataclasses import replace
from pathlib import Path

from slither_bot.adapter import GameAdapter
from slither_bot.app import Application
from slither_bot.browser import PlaywrightGameBrowser
from slither_bot.config import Config
from slither_bot.controller import InputController
from slither_bot.fixture_adapter import FixtureAdapter
from slither_bot.model import BaselineAgent
from slither_bot.observer import SnapshotObserver
from slither_bot.replay import BoundedReplay
from slither_bot.reward import LengthReward
from slither_bot.slither_adapter import SlitherAdapter
from slither_bot.storage import RunStorage
from slither_bot.train import ModelWorker, Trainer
from slither_bot.types import ControlMode


def build(config: Config) -> Application:
    controller = InputController(config.runtime.initial_mode)
    adapter: GameAdapter = (
        SlitherAdapter(config.runtime.sectors, config.nickname)
        if config.target == "slither"
        else FixtureAdapter(config.runtime.sectors, config.browser.fixture_lifetime_s)
    )
    browser = PlaywrightGameBrowser(
        config,
        controller,
        adapter,
    )
    agent = BaselineAgent(config.agent, config.seed)
    worker = ModelWorker()
    return Application(
        config,
        browser,
        SnapshotObserver(config.runtime.sectors),
        controller,
        agent,
        LengthReward(**vars(config.reward)),
        BoundedReplay(config.training.replay_capacity, config.seed),
        RunStorage(config.runs_dir, config),
        worker,
        Trainer(agent, worker, config.training),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Play and record at http://slither.com/io using headed Chromium"
    )
    parser.add_argument("--target", choices=["slither", "fixture"], help="Default: slither website")
    parser.add_argument("--nickname", help="Nickname for the Slither website")
    parser.add_argument("--config", type=Path, help="Nested JSON configuration file")
    parser.add_argument("--headless", action="store_true", help="For automated smoke checks")
    parser.add_argument("--mode", choices=["AI", "HUMAN"])
    parser.add_argument("--agent", choices=["deterministic", "random"])
    parser.add_argument("--hz", type=float)
    parser.add_argument("--episodes", type=int, help="Stop after N episodes (0 means unlimited)")
    parser.add_argument("--seconds", type=float, help="Maximum run time (0 means unlimited)")
    parser.add_argument("--runs-dir", type=Path)
    parser.add_argument("--seed", type=int)
    parser.add_argument(
        "--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"]
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=args.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    try:
        config = Config.load(args.config) if args.config else Config()
        runtime = replace(
            config.runtime,
            **{
                key: value
                for key, value in {
                    "initial_mode": ControlMode(args.mode) if args.mode else None,
                    "control_hz": args.hz,
                    "max_episodes": args.episodes,
                    "run_seconds": args.seconds,
                }.items()
                if value is not None
            },
        )
        config = replace(
            config,
            runtime=runtime,
            browser=replace(config.browser, headless=args.headless or config.browser.headless),
            **{
                key: value
                for key, value in {
                    "runs_dir": args.runs_dir,
                    "seed": args.seed,
                    "agent": args.agent,
                    "target": args.target,
                    "nickname": args.nickname,
                }.items()
                if value is not None
            },
        )
        asyncio.run(build(config).run())
    except KeyboardInterrupt:
        logging.info("Stopped by user")
    except (ValueError, TypeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
