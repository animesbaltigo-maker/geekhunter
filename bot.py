"""Launcher: starts autoposting and the multi-user Telegram bot together."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from autopost_bot import run_autopost, setup_logging
from config import load_settings
from multiuser_bot import MultiUserBot

log = logging.getLogger(__name__)
_LOCK_FILE = None


def acquire_single_instance_lock() -> bool:
    global _LOCK_FILE
    lock_path = Path("data/bot.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    _LOCK_FILE = lock_path.open("a+", encoding="utf-8")
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(_LOCK_FILE.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(_LOCK_FILE.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    _LOCK_FILE.seek(0)
    _LOCK_FILE.truncate()
    _LOCK_FILE.write(f"pid={os.getpid()} platform={sys.platform}\n")
    _LOCK_FILE.flush()
    return True


async def main() -> None:
    parser = argparse.ArgumentParser(description="ML Affiliate Bot launcher.")
    parser.add_argument("--once", action="store_true", help="Roda apenas uma rodada da autopostagem.")
    parser.add_argument("--post", action="store_true", help="Posta de verdade na autopostagem.")
    parser.add_argument("--dry-run", action="store_true", help="Forca modo teste na autopostagem.")
    parser.add_argument("--ignore-history", action="store_true", help="Nao pula produtos repetidos na autopostagem.")
    parser.add_argument("--only-auto", action="store_true", help="Liga apenas a autopostagem.")
    parser.add_argument("--only-multiuser", action="store_true", help="Liga apenas o bot multiusuario.")
    args = parser.parse_args()

    setup_logging()
    if not acquire_single_instance_lock():
        log.error("Ja existe um python bot.py rodando. Feche a outra instancia antes de abrir de novo.")
        return

    settings = load_settings()

    if args.post or (not args.dry_run and not args.once):
        object.__setattr__(settings, "dry_run", False)
    if args.dry_run:
        object.__setattr__(settings, "dry_run", True)

    if args.only_multiuser:
        await MultiUserBot().run()
        return

    if args.once or args.only_auto:
        await run_autopost(settings, ignore_history=args.ignore_history, run_once=args.once)
        return

    log.info("Launcher ativo: autopostagem + multiusuario.")
    await asyncio.gather(
        run_autopost(settings, ignore_history=args.ignore_history, run_once=False),
        MultiUserBot().run(),
    )


if __name__ == "__main__":
    asyncio.run(main())
