"""Bounded execution for blocking service work.

Most RETICLE data access is synchronous (psycopg2, sqlite3, NumPy and urllib).
Calling it directly from an ``async def`` route blocks Uvicorn's event loop and
can make even ``/api/health`` unresponsive.  This module keeps that work in
worker threads and, unlike Starlette's shared 40-thread default pool, gives each
workload a deliberately small concurrency and queue budget.

The admission limiter is separate from the worker limiter.  That bounds both
running and queued requests, so a slow dependency cannot create an unbounded
in-process backlog. LLM traffic has its own worker quota; workloads can still
share physical dependencies such as RDS, whose pool remains the final bound.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Coroutine
from functools import partial, wraps
from time import monotonic
from typing import Any, ParamSpec, TypeVar, cast

import anyio

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


class ServiceOverloaded(RuntimeError):
    """Raised when a workload's bounded admission queue is full for too long."""

    def __init__(self, workload: str, retry_after: int = 2) -> None:
        super().__init__(f"{workload} service is busy; retry shortly")
        self.workload = workload
        self.retry_after = retry_after


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        logger.warning("Ignoring invalid %s; using %d", name, default)
        return default
    if value < 1:
        logger.warning("Ignoring non-positive %s; using %d", name, default)
        return default
    return value


def _positive_float(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        logger.warning("Ignoring invalid %s; using %.1f", name, default)
        return default
    if value <= 0:
        logger.warning("Ignoring non-positive %s; using %.1f", name, default)
        return default
    return value


def _nonnegative_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        logger.warning("Ignoring invalid %s; using %d", name, default)
        return default
    if value < 0:
        logger.warning("Ignoring negative %s; using %d", name, default)
        return default
    return value


class _Workload:
    """A workload's concurrency budget.

    The limiters are built on first use rather than in ``__init__``. Under the
    pinned anyio (3.7.1, forced by ``fastapi==0.104.1``), ``CapacityLimiter`` is
    constructed through the *running* async backend, so building one at import
    time raises ``AsyncLibraryNotFoundError`` and the whole API fails to import.
    Deferring to first use means they are created inside the event loop, which
    works on both 3.x and 4.x.
    """

    def __init__(self, name: str, workers: int, queue: int, queue_timeout: float) -> None:
        self.name = name
        self.worker_tokens = workers
        # Admission includes the running workers plus the bounded waiting room.
        self.admission_tokens = workers + queue
        self.queue_timeout = queue_timeout
        self._workers: Any = None
        self._admission: Any = None

    # Only ever reached from async code, so the check-then-assign cannot race:
    # a single event loop gives no other task a chance to run in between.
    @property
    def workers(self) -> Any:
        if self._workers is None:
            self._workers = anyio.CapacityLimiter(self.worker_tokens)
        return self._workers

    @property
    def admission(self) -> Any:
        if self._admission is None:
            self._admission = anyio.CapacityLimiter(self.admission_tokens)
        return self._admission


# How long a caller waits for a worker before being turned away.
#
# THIS IS PER WORKLOAD, AND IT HAS TO BE. One shared value shipped, at 1.0s, and it
# made /api/query unusable: that endpoint runs on `cpu`, takes 8-10 seconds, and has
# one worker. A one-second admission timeout in front of an eight-second job cannot
# ever be satisfied — the queue is guaranteed to still be occupied when the timer
# expires — so the second person to ask for an analysis was rejected, every time.
# Measured against the deployed API: four concurrent /api/query, three of them 503
# after 1.3s with "cpu service is busy".
#
# So the number belongs to the job, not to the service. A gene lookup that normally
# answers in 100ms should shed load after a second, because a client waiting longer
# than that has already lost. An analysis the user explicitly started and is watching
# a progress bar for should queue, because they will wait and they have nowhere else
# to go. The rule is roughly: as long as the work itself typically takes.
#
# AND NOTHING MAY EXCEED THE GATEWAY. CloudFront gives the origin 30 seconds and
# then returns its own 504, so a queue that would hold someone for 45s does not buy
# them an answer — it buys them a half-minute stare ending in a gateway error page,
# which is a strictly worse failure than being told to retry. Measured: five
# concurrent /api/query served at 8.3s, 16.5s and 24.6s, the last two killed at
# exactly 30.2s by CloudFront. Every timeout below stays under that ceiling, and a
# workload's queue is only as deep as it can drain inside it.
_GATEWAY_CEILING = _positive_float("RETICLE_GATEWAY_TIMEOUT", 30.0)
_TIMEOUT_DB = _positive_float("RETICLE_DB_QUEUE_TIMEOUT", 1.0)
_TIMEOUT_CPU = _positive_float("RETICLE_CPU_QUEUE_TIMEOUT", 26.0)
_TIMEOUT_EXTERNAL = _positive_float("RETICLE_EXTERNAL_QUEUE_TIMEOUT", 6.0)
_TIMEOUT_LLM = _positive_float("RETICLE_LLM_QUEUE_TIMEOUT", 3.0)

_WORKLOADS = {
    # Keep this well below the 16-slot psycopg pool and the small RDS instance.
    "db": _Workload(
        "db",
        _positive_int("RETICLE_DB_WORKERS", 3),
        _nonnegative_int("RETICLE_DB_QUEUE", 3),
        _TIMEOUT_DB,
    ),
    # The ECS task currently has 0.25 vCPU; parallel NumPy jobs hurt more than help,
    # so this stays at one worker and gets its depth from the queue instead. Two deep:
    # at ~8s a job the third in line finishes around 24s, inside the gateway's 30. A
    # fourth caller is told to retry immediately, which is the honest answer — there
    # is no arrangement of this queue that could have served them in time.
    "cpu": _Workload(
        "cpu",
        _positive_int("RETICLE_CPU_WORKERS", 1),
        _nonnegative_int("RETICLE_CPU_QUEUE", 2),
        _TIMEOUT_CPU,
    ),
    "external": _Workload(
        "external",
        _positive_int("RETICLE_EXTERNAL_WORKERS", 2),
        _nonnegative_int("RETICLE_EXTERNAL_QUEUE", 4),
        _TIMEOUT_EXTERNAL,
    ),
    # Keep slow LLM gateway waits out of the deterministic endpoint worker slots.
    # Any DB lookup inside an LLM job is still bounded by the shared DB pool.
    #
    # No waiting room, deliberately. A measured round trip to the WashU gateway is
    # 24.1s against a 30s CloudFront ceiling, so one call barely fits and a second
    # one queued behind it cannot fit at all — it would wait out the first and then
    # be killed by the gateway. There is no queue depth that helps here, so a caller
    # who arrives while the worker is busy is told to retry straight away.
    "llm": _Workload(
        "llm",
        _positive_int("RETICLE_LLM_WORKERS", 1),
        _nonnegative_int("RETICLE_LLM_QUEUE", 0),
        _TIMEOUT_LLM,
    ),
}


async def run_blocking(
    func: Callable[..., R],
    *args: Any,
    workload: str = "db",
    **kwargs: Any,
) -> R:
    """Run ``func`` off the event loop under a bounded workload budget."""

    group = _WORKLOADS.get(workload)
    if group is None:
        raise ValueError(f"Unknown blocking workload: {workload}")

    admitted = False
    worker_acquired = False
    try:
        with anyio.move_on_after(group.queue_timeout) as scope:
            await group.admission.acquire()
            admitted = True
            await group.workers.acquire()
            worker_acquired = True
    except BaseException:
        # A client can disconnect while this task is waiting for a worker. A
        # parent-scope cancellation is not swallowed by move_on_after, so clean
        # up every token already acquired before propagating it.
        if worker_acquired:
            group.workers.release()
        if admitted:
            group.admission.release()
        raise
    if scope.cancel_called or not worker_acquired:
        if worker_acquired:
            group.workers.release()
        if admitted:
            group.admission.release()
        logger.warning(
            "Rejecting %s work: queue wait exceeded %.2fs",
            workload,
            group.queue_timeout,
        )
        raise ServiceOverloaded(workload)

    started = monotonic()
    try:
        call = partial(func, *args, **kwargs)
        # Not abandoning on cancel is intentional: a disconnected client cannot
        # release capacity while its database query is still running.
        # The workload token is acquired explicitly above so its wait can time
        # out. The AnyIO default limiter is only the physical thread-pool cap;
        # workload concurrency remains governed by ``group.workers``.
        #
        # Spelled ``cancellable`` rather than ``abandon_on_cancel``: fastapi
        # 0.104.1 requires anyio<4.0.0, and 3.x has no ``abandon_on_cancel``
        # keyword, so that spelling raises TypeError on every offloaded call.
        # ``cancellable`` is accepted by both 3.x and 4.x, so this keeps working
        # if the pin is ever raised.
        result = await anyio.to_thread.run_sync(call, cancellable=False)
        return cast(R, result)
    finally:
        group.workers.release()
        group.admission.release()
        elapsed = monotonic() - started
        if elapsed >= 5:
            logger.warning("Slow %s work completed in %.2fs", workload, elapsed)


def offload(workload: str = "db") -> Callable[
    [Callable[P, R]], Callable[P, Coroutine[Any, Any, R]]
]:
    """Expose a synchronous service function through an async offloaded wrapper."""

    if workload not in _WORKLOADS:
        raise ValueError(f"Unknown blocking workload: {workload}")

    def decorate(func: Callable[P, R]) -> Callable[P, Coroutine[Any, Any, R]]:
        @wraps(func)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            return await run_blocking(func, *args, workload=workload, **kwargs)

        return wrapped

    return decorate


def blocking_target(
    func: Callable[P, Coroutine[Any, Any, R]],
) -> Callable[P, R]:
    """Return the synchronous target behind an :func:`offload` wrapper.

    This is only for code that is *already* running in a managed worker thread
    and needs to compose service functions without starting a nested event loop.
    """

    target = getattr(func, "__wrapped__", None)
    if target is None:
        raise TypeError("function is not an offload wrapper")
    return cast(Callable[P, R], target)


def workload_limits() -> dict[str, dict[str, int | float]]:
    """Return configured limits for diagnostics and tests (never mutable internals)."""

    # Reads the configured counts, not the limiters: this reports configuration,
    # and it must stay callable from sync code (diagnostics, tests) where the
    # lazily-built limiters have no running loop to be created in.
    return {
        name: {
            "workers": group.worker_tokens,
            "admission": group.admission_tokens,
            "queue_timeout_seconds": group.queue_timeout,
        }
        for name, group in _WORKLOADS.items()
    }
