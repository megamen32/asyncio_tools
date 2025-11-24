# async_tools.py
# Tiny asyncio task utility library (single-file, no deps).
# Python 3.10+

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import (
    Any, Awaitable, Callable, Iterable, List, Optional, Sequence, Tuple, Type, Union
)

AwaitableOrFunc = Union[Awaitable[Any], Callable[[], Awaitable[Any]]]


@dataclass
class RunSummary:
    results: List[Any]                 # successful results in input order; failed -> None
    errors: List[Tuple[int, BaseException]]  # (index, exception)
    cancelled: bool                    # True if we cancelled pending tasks


class FirstSuccessError(RuntimeError):
    """Raised by wait_first when all tasks fail."""
    def __init__(self, errors: List[Tuple[int, BaseException]]):
        super().__init__("All tasks failed; no successful result.")
        self.errors = errors


def _normalize_awaitable(x: AwaitableOrFunc) -> Awaitable[Any]:
    return x() if callable(x) else x


def chunked(seq: Sequence[Any], size: int) -> Iterable[List[Any]]:
    """Yield chunks of `seq` with max length `size`."""
    if size <= 0:
        raise ValueError("size must be > 0")
    for i in range(0, len(seq), size):
        yield list(seq[i:i + size])


async def run_tasks(
    tasks: Sequence[AwaitableOrFunc],
    *,
    parallel: bool = True,
    stop_on_error: bool = False,
    limit: Optional[int] = None,
) -> RunSummary:
    """
    Run tasks sequentially or in parallel.

    - parallel=True: run concurrently (optionally limited by `limit`)
    - parallel=False: run one-by-one in given order
    - stop_on_error=True: cancel remaining tasks on first error
    - stop_on_error=False: collect all errors, keep going
    """
    if not tasks:
        return RunSummary(results=[], errors=[], cancelled=False)

    if not parallel:
        results: List[Any] = []
        errors: List[Tuple[int, BaseException]] = []
        for i, t in enumerate(tasks):
            try:
                res = await _normalize_awaitable(t)
                results.append(res)
            except BaseException as e:  # includes CancelledError intentionally
                errors.append((i, e))
                results.append(None)
                if stop_on_error:
                    return RunSummary(results=results, errors=errors, cancelled=False)
        return RunSummary(results=results, errors=errors, cancelled=False)

    sem = asyncio.Semaphore(limit) if limit and limit > 0 else None

    async def _run_one(i: int, t: AwaitableOrFunc):
        if sem is None:
            return await _normalize_awaitable(t)
        async with sem:
            return await _normalize_awaitable(t)

    loop = asyncio.get_running_loop()
    created: List[asyncio.Task] = []
    index_by_task: dict[asyncio.Task, int] = {}

    for i, t in enumerate(tasks):
        task = loop.create_task(_run_one(i, t))
        created.append(task)
        index_by_task[task] = i

    results: List[Any] = [None] * len(tasks)
    errors: List[Tuple[int, BaseException]] = []
    cancelled = False

    if stop_on_error:
        done, pending = await asyncio.wait(created, return_when=asyncio.FIRST_EXCEPTION)
        # process done (might include successes)
        for d in done:
            i = index_by_task[d]
            try:
                results[i] = await d
            except BaseException as e:
                errors.append((i, e))

        # if any error -> cancel all pending
        if errors and pending:
            cancelled = True
            for p in pending:
                p.cancel()
            # drain pending to silence warnings
            for p in pending:
                i = index_by_task[p]
                try:
                    results[i] = await p
                except BaseException as e:
                    errors.append((i, e))
        else:
            # no error; finish pending
            if pending:
                more_done, _ = await asyncio.wait(pending)
                for d in more_done:
                    i = index_by_task[d]
                    try:
                        results[i] = await d
                    except BaseException as e:
                        errors.append((i, e))

        return RunSummary(results=results, errors=errors, cancelled=cancelled)

    # stop_on_error=False: gather all, keep order
    gathered = await asyncio.gather(*created, return_exceptions=True)
    for i, g in enumerate(gathered):
        if isinstance(g, BaseException):
            errors.append((i, g))
            results[i] = None
        else:
            results[i] = g
    return RunSummary(results=results, errors=errors, cancelled=False)


async def retry(
    coro_or_func: AwaitableOrFunc,
    *,
    retries: int = 3,
    delay: float = 0.5,
    backoff: float = 2.0,
    exceptions: Tuple[Type[BaseException], ...] = (Exception,),
) -> Any:
    """Retry awaitable up to `retries` times on matching exceptions."""
    if retries < 0:
        raise ValueError("retries must be >= 0")
    attempt = 0
    wait = delay
    while True:
        try:
            return await _normalize_awaitable(coro_or_func)
        except exceptions as e:
            if attempt >= retries:
                raise
            attempt += 1
            if wait > 0:
                await asyncio.sleep(wait)
            wait *= backoff


async def with_timeout(coro_or_func: AwaitableOrFunc, timeout: float) -> Any:
    """Run awaitable with timeout (raises asyncio.TimeoutError)."""
    return await asyncio.wait_for(_normalize_awaitable(coro_or_func), timeout=timeout)


async def race(tasks: Sequence[AwaitableOrFunc]) -> Tuple[Any, int]:
    """
    Return (result, index) of the first completed task (success or error).
    Cancels the rest.
    """
    if not tasks:
        raise ValueError("tasks is empty")
    created = [asyncio.create_task(_normalize_awaitable(t)) for t in tasks]
    try:
        done, pending = await asyncio.wait(created, return_when=asyncio.FIRST_COMPLETED)
        winner = next(iter(done))
        idx = created.index(winner)
        res = await winner  # may raise
        return res, idx
    finally:
        for t in created:
            if not t.done():
                t.cancel()
        await asyncio.gather(*created, return_exceptions=True)


async def wait_first(tasks: Sequence[AwaitableOrFunc]) -> Any:
    """
    Return the first *successful* result.
    Cancels the rest. If all fail -> FirstSuccessError.
    """
    if not tasks:
        raise ValueError("tasks is empty")

    created = [asyncio.create_task(_normalize_awaitable(t)) for t in tasks]
    errors: List[Tuple[int, BaseException]] = []
    try:
        for fut in asyncio.as_completed(created):
            idx = created.index(fut)  # ok for small lists
            try:
                res = await fut
                # success -> cancel others
                for t in created:
                    if t is not fut and not t.done():
                        t.cancel()
                await asyncio.gather(*created, return_exceptions=True)
                return res
            except BaseException as e:
                errors.append((idx, e))
        raise FirstSuccessError(errors)
    finally:
        for t in created:
            if not t.done():
                t.cancel()
        await asyncio.gather(*created, return_exceptions=True)


async def limit_concurrency(tasks: Sequence[AwaitableOrFunc], limit: int) -> RunSummary:
    """Convenience wrapper for parallel limited execution."""
    return await run_tasks(tasks, parallel=True, stop_on_error=False, limit=limit)


async def consume(
    items: Sequence[Any],
    *,
    worker: Callable[[Any], Awaitable[Any]],
    limit: Optional[int] = None,
    stop_on_error: bool = False,
) -> RunSummary:
    """Map items through async worker with optional concurrency limit."""
    coros = [lambda item=item: worker(item) for item in items]
    return await run_tasks(coros, parallel=True, stop_on_error=stop_on_error, limit=limit)


async def log_errors(
    tasks: Sequence[AwaitableOrFunc],
    *,
    logger: Any,
    parallel: bool = True,
    limit: Optional[int] = None,
) -> RunSummary:
    """Run tasks and log all errors via logger.exception."""
    summary = await run_tasks(tasks, parallel=parallel, stop_on_error=False, limit=limit)
    for i, e in summary.errors:
        logger.exception(f"Task {i} failed", exc_info=e)
    return summary


def run_periodic(
    func: Callable[[], Awaitable[Any]],
    interval: float,
    *,
    run_immediately: bool = True,
    logger: Any = None,
) -> asyncio.Task:
    """
    Start periodic background task. Returns asyncio.Task you can cancel.
    """
    async def _loop():
        try:
            if run_immediately:
                await func()
            while True:
                await asyncio.sleep(interval)
                await func()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if logger is not None:
                logger.exception(f"Periodic task crashed", exc_info=e)
            else:
                raise

    return asyncio.create_task(_loop())


async def timeout_or_cancel(
    tasks: Sequence[AwaitableOrFunc],
    timeout: float,
    *,
    limit: Optional[int] = None,
) -> RunSummary:
    """
    Run tasks in parallel with global timeout.
    If timeout reached, cancel pending and return partial results.
    """
    if not tasks:
        return RunSummary(results=[], errors=[], cancelled=False)

    sem = asyncio.Semaphore(limit) if limit and limit > 0 else None

    async def _run_one(i: int, t: AwaitableOrFunc):
        if sem is None:
            return await _normalize_awaitable(t)
        async with sem:
            return await _normalize_awaitable(t)

    created = [asyncio.create_task(_run_one(i, t)) for i, t in enumerate(tasks)]
    results: List[Any] = [None] * len(tasks)
    errors: List[Tuple[int, BaseException]] = []
    cancelled = False

    done, pending = await asyncio.wait(created, timeout=timeout)

    for d in done:
        i = created.index(d)
        try:
            results[i] = await d
        except BaseException as e:
            errors.append((i, e))

    if pending:
        cancelled = True
        for p in pending:
            p.cancel()
        pending_results = await asyncio.gather(*pending, return_exceptions=True)
        for p, pr in zip(pending, pending_results):
            i = created.index(p)
            if isinstance(pr, BaseException):
                errors.append((i, pr))

    return RunSummary(results=results, errors=errors, cancelled=cancelled)


async def measure(coro_or_func: AwaitableOrFunc) -> Tuple[Any, float]:
    """Return (result, seconds)."""
    t0 = time.perf_counter()
    res = await _normalize_awaitable(coro_or_func)
    return res, time.perf_counter() - t0
