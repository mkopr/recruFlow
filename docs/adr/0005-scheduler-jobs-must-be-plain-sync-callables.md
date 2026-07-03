# Scheduler job callables must be plain `def`, not `async def`

The scheduler (US15) uses APScheduler's `AsyncIOScheduler`, which shares FastAPI/uvicorn's single
asyncio event loop rather than running a separate thread or process. `AsyncIOScheduler`'s default
executor only offloads a job to its thread pool when the registered callable is a plain (non-`async
def`) function; an `async def` callable is instead scheduled directly on the main event loop via
`ensure_future`.

None of the three connectors (`solid_jobs`, `justjoinit`, `nofluffjobs`) are actually non-blocking:
`solid_jobs.py` shells out via a blocking `subprocess.run`, and `justjoinit.py`/`nofluffjobs.py`
call `httpx.get` synchronously — all three happen to be wrapped in `async def` functions, but none
of them `await` anything that yields control back to the loop. Registering an `async def` scheduler
job that transitively calls these connectors would therefore block the *entire* API — every other
request, including `/health` — for the duration of every scheduled or manually triggered run
(observed: tens of seconds for a JustJoin.it pagination run).

`app.scheduler.service.run_source_sync` is therefore a plain `def`, not `async def`. It builds its
own throwaway `AsyncEngine`/sessionmaker and drives the actual async work via a fresh
`asyncio.run(...)` call, since it executes inside a worker thread with no event loop of its own —
it cannot reuse `app.api.deps`'s process-wide sessionmaker, which is pinned to the main loop's
connection pool. `register_jobs` passes `run_source_sync` (not a coroutine function) to
`scheduler.add_job(...)`, and the manual-trigger endpoint's async wrapper (`run_source`) calls it
via `asyncio.to_thread(...)` for the same reason, so automatic and manual runs share one code path
and both stay off the main loop.

**Do not "simplify" this into an `async def` job function that awaits the connectors directly** —
it looks like the more idiomatic asyncio pattern, but given the connectors' current blocking
implementation it silently reintroduces full-API blocking during every ingestion run, which is the
exact defect this story's acceptance criteria ("scheduled jobs run without blocking the API from
serving other requests") exists to prevent. This is verified mechanically by
`tests/integration/test_scheduler_routes.py::test_health_endpoint_responds_during_scheduler_run`.
