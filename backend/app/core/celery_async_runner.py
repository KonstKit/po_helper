from __future__ import annotations

import asyncio
import logging
from threading import RLock
from typing import Any, Coroutine, TypeVar

from celery import signals

logger = logging.getLogger(__name__)

T = TypeVar("T")

_loop: asyncio.AbstractEventLoop | None = None
_loop_lock = RLock()


def _get_or_create_loop() -> asyncio.AbstractEventLoop:
    global _loop

    with _loop_lock:
        if _loop is None or _loop.is_closed():
            _loop = asyncio.new_event_loop()
            logger.debug("Created shared Celery async event loop id=%s", id(_loop))
        return _loop


def run_async(coro: Coroutine[Any, Any, T]) -> T:
    """
    Run coroutine on a shared event loop per Celery worker process.

    A single reusable loop avoids cross-loop Future attachment issues
    caused by repeatedly creating/closing loops for every task.
    """
    loop = _get_or_create_loop()
    try:
        return loop.run_until_complete(coro)
    except RuntimeError as exc:
        if "Event loop is closed" not in str(exc):
            raise
        logger.warning("Recreating shared Celery async loop after closure: %s", exc)
        close_async_loop()
        return _get_or_create_loop().run_until_complete(coro)


def close_async_loop() -> None:
    """Close shared loop on worker shutdown to release async resources."""
    global _loop

    with _loop_lock:
        loop = _loop
        _loop = None

    if loop is None or loop.is_closed():
        return

    try:
        pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.run_until_complete(loop.shutdown_asyncgens())
    except Exception as exc:  # pragma: no cover - defensive cleanup
        logger.debug("Failed to fully drain shared Celery loop: %s", exc)
    finally:
        loop.close()
        logger.debug("Closed shared Celery async event loop")


@signals.worker_process_shutdown.connect
def _close_loop_on_process_shutdown(*_args: Any, **_kwargs: Any) -> None:
    close_async_loop()


@signals.worker_shutdown.connect
def _close_loop_on_worker_shutdown(*_args: Any, **_kwargs: Any) -> None:
    close_async_loop()
