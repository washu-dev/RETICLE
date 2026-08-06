import threading
from collections.abc import Callable

import anyio
import httpx
import pytest
from fastapi.testclient import TestClient

from main import app
from routers import coessential, llm_aaron
from services import execution


async def _wait_until(predicate: Callable[[], bool], timeout: float = 0.5) -> None:
    """Cooperatively wait for a worker-thread observation without blocking the loop."""
    with anyio.fail_after(timeout):
        while not predicate():
            await anyio.sleep(0.001)


def test_run_blocking_keeps_event_loop_responsive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        group = execution._Workload("cpu", workers=1, queue=1, queue_timeout=0.1)
        monkeypatch.setitem(execution._WORKLOADS, "cpu", group)

        started = threading.Event()
        finished = threading.Event()
        release = threading.Event()
        results: list[int] = []

        def blocking_work() -> int:
            started.set()
            if not release.wait(1):
                raise AssertionError("test did not release blocking worker")
            finished.set()
            return 42

        async def invoke() -> None:
            results.append(await execution.run_blocking(blocking_work, workload="cpu"))

        try:
            async with anyio.create_task_group() as tasks:
                tasks.start_soon(invoke)
                await _wait_until(started.is_set)

                # Reaching this assertion while the synchronous function is still
                # waiting proves that it is not occupying the event-loop thread.
                assert not finished.is_set()
                release.set()
        finally:
            release.set()

        assert results == [42]

    anyio.run(scenario)


def test_health_responds_while_expensive_endpoint_is_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        group = execution._Workload("cpu", workers=1, queue=0, queue_timeout=0.1)
        monkeypatch.setitem(execution._WORKLOADS, "cpu", group)

        started = threading.Event()
        release = threading.Event()
        expensive_response: list[httpx.Response] = []

        def blocking_feature() -> dict:
            started.set()
            if not release.wait(1):
                raise AssertionError("test did not release expensive endpoint")
            return {"focus": "TP53", "nodes": [], "edges": []}

        async def slow_coessential(_symbol: str, _organism: str) -> dict:
            return await execution.run_blocking(blocking_feature, workload="cpu")

        monkeypatch.setattr(coessential, "get_coessential", slow_coessential)
        # TestClient is synchronous and would serialise these two requests, which is
        # exactly what this test needs to disprove, so it drives the app directly.
        # httpx 0.24.1 types the ASGI app as taking plain dicts while Starlette
        # declares MutableMapping; the two are compatible at runtime and mypy has no
        # way to see that, so the mismatch is silenced rather than worked around.
        transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            async def call_expensive_endpoint() -> None:
                expensive_response.append(
                    await client.get("/api/coessential", params={"symbol": "TP53"})
                )

            try:
                async with anyio.create_task_group() as tasks:
                    tasks.start_soon(call_expensive_endpoint)
                    await _wait_until(started.is_set)

                    with anyio.fail_after(0.2):
                        health = await client.get("/api/health")
                    assert health.status_code == 200
                    release.set()
            finally:
                release.set()

        assert expensive_response[0].status_code == 200

    anyio.run(scenario)


def test_full_admission_queue_raises_service_overloaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        group = execution._Workload("db", workers=1, queue=1, queue_timeout=0.03)
        monkeypatch.setitem(execution._WORKLOADS, "db", group)

        first_started = threading.Event()
        release = threading.Event()
        completed: list[str] = []
        rejected: list[str] = []

        def queued_work(label: str) -> str:
            first_started.set()
            if not release.wait(1):
                raise AssertionError("test did not release queued worker")
            return label

        async def invoke(label: str) -> None:
            try:
                completed.append(
                    await execution.run_blocking(queued_work, label, workload="db")
                )
            except execution.ServiceOverloaded:
                rejected.append(label)

        try:
            async with anyio.create_task_group() as tasks:
                tasks.start_soon(invoke, "running")
                await _wait_until(first_started.is_set)
                tasks.start_soon(invoke, "queued")
                await _wait_until(lambda: group.admission.borrowed_tokens == 2)

                with pytest.raises(execution.ServiceOverloaded) as raised:
                    await execution.run_blocking(lambda: "never-runs", workload="db")

                assert raised.value.workload == "db"
                assert raised.value.retry_after == 2
                release.set()
        finally:
            release.set()

        assert completed == ["running"]
        assert rejected == ["queued"]

    anyio.run(scenario)


def test_admitted_request_times_out_waiting_for_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        group = execution._Workload("db", workers=1, queue=1, queue_timeout=0.03)
        monkeypatch.setitem(execution._WORKLOADS, "db", group)

        started = threading.Event()
        release = threading.Event()

        def occupy_worker() -> None:
            started.set()
            if not release.wait(1):
                raise AssertionError("test did not release occupied worker")

        async def occupy() -> None:
            await execution.run_blocking(occupy_worker, workload="db")

        try:
            async with anyio.create_task_group() as tasks:
                tasks.start_soon(occupy)
                await _wait_until(started.is_set)

                # This request fits in the waiting room but cannot acquire the
                # worker. It must fail promptly rather than wait for the whole
                # duration of the first database/LLM call.
                with pytest.raises(execution.ServiceOverloaded):
                    await execution.run_blocking(lambda: None, workload="db")
                assert group.admission.borrowed_tokens == 1
                release.set()
        finally:
            release.set()

    anyio.run(scenario)


def test_cancelled_waiter_releases_admission_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        group = execution._Workload("db", workers=1, queue=1, queue_timeout=1)
        monkeypatch.setitem(execution._WORKLOADS, "db", group)

        started = threading.Event()
        release = threading.Event()
        waiter_done = anyio.Event()
        waiter_scope: list[anyio.CancelScope] = []

        def occupy_worker() -> None:
            started.set()
            if not release.wait(1):
                raise AssertionError("test did not release occupied worker")

        async def occupy() -> None:
            await execution.run_blocking(occupy_worker, workload="db")

        async def wait_then_cancel() -> None:
            try:
                with anyio.CancelScope() as scope:
                    waiter_scope.append(scope)
                    await execution.run_blocking(lambda: None, workload="db")
            finally:
                waiter_done.set()

        try:
            async with anyio.create_task_group() as tasks:
                tasks.start_soon(occupy)
                await _wait_until(started.is_set)
                tasks.start_soon(wait_then_cancel)
                await _wait_until(lambda: group.admission.borrowed_tokens == 2)

                waiter_scope[0].cancel()
                await waiter_done.wait()

                assert group.admission.borrowed_tokens == 1
                assert group.workers.borrowed_tokens == 1
                release.set()
        finally:
            release.set()

    anyio.run(scenario)


def test_llm_route_preserves_overload_503(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def overloaded(_gene: str, _taxid: int) -> dict:
        raise execution.ServiceOverloaded("llm", retry_after=7)

    monkeypatch.setattr(llm_aaron, "get_screen_analysis", overloaded)

    response = client.get("/api/screen_analysis", params={"gene": "TP53"})

    assert response.status_code == 503
    assert response.headers["retry-after"] == "7"
    assert response.json() == {
        "detail": "llm service is busy; retry shortly",
        "workload": "llm",
    }


@pytest.mark.parametrize(
    ("saturated_workload", "free_workload"),
    [("db", "llm"), ("llm", "db")],
)
def test_db_and_llm_quotas_are_isolated(
    saturated_workload: str,
    free_workload: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        db_group = execution._Workload("db", workers=1, queue=0, queue_timeout=0.05)
        llm_group = execution._Workload("llm", workers=1, queue=0, queue_timeout=0.05)
        monkeypatch.setitem(execution._WORKLOADS, "db", db_group)
        monkeypatch.setitem(execution._WORKLOADS, "llm", llm_group)

        started = threading.Event()
        release = threading.Event()

        def occupy_quota() -> None:
            started.set()
            if not release.wait(1):
                raise AssertionError("test did not release saturated workload")

        async def occupy() -> None:
            await execution.run_blocking(occupy_quota, workload=saturated_workload)

        try:
            async with anyio.create_task_group() as tasks:
                tasks.start_soon(occupy)
                await _wait_until(started.is_set)

                # The other workload must retain its own worker/admission token.
                with anyio.fail_after(0.2):
                    result = await execution.run_blocking(
                        lambda: "available", workload=free_workload
                    )
                assert result == "available"
                release.set()
        finally:
            release.set()

    anyio.run(scenario)
