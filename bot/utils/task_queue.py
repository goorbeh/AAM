"""A simple bounded-concurrency async task queue.

Keeps at most `max_concurrency` CPU-heavy jobs (like image upscaling)
running at once, so a burst of requests can't overload a small CPU-only
server. Extra jobs wait in an internal asyncio.Queue instead of all
starting at once.
"""

import asyncio
import logging
from typing import Any, Callable, Coroutine, List

logger = logging.getLogger(__name__)

CoroFactory = Callable[[], Coroutine[Any, Any, None]]


class TaskQueue:
    def __init__(self, max_concurrency: int = 1):
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        self._queue: "asyncio.Queue[CoroFactory]" = asyncio.Queue()
        self._max_concurrency = max_concurrency
        self._workers: List[asyncio.Task] = []
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        for _ in range(self._max_concurrency):
            self._workers.append(asyncio.create_task(self._worker_loop()))
        logger.info("TaskQueue started with %d worker(s).", self._max_concurrency)

    async def stop(self) -> None:
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        self._started = False

    async def submit(self, coro_factory: CoroFactory) -> None:
        """`coro_factory` must be a zero-argument callable that RETURNS a
        coroutine (e.g. `lambda: process_image(path)`), not the coroutine
        itself - this way the coroutine is only created once a worker
        actually picks up the job, not when it's queued."""
        await self._queue.put(coro_factory)

    async def _worker_loop(self) -> None:
        while True:
            try:
                coro_factory = await self._queue.get()
            except asyncio.CancelledError:
                break

            try:
                await coro_factory()
            except Exception:
                logger.exception("Unhandled error while processing a queued task")
            finally:
                self._queue.task_done()
