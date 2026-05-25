from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from tri_timing_service.runtime import RaceRuntime
from tri_timing_service.settings import ServiceSettings


def create_app(
    settings: ServiceSettings | None = None,
    database_path: Path | None = None,
) -> FastAPI:
    service_settings = settings or ServiceSettings.for_tests()
    runtime: RaceRuntime | None = None

    def get_runtime() -> RaceRuntime:
        if runtime is None:
            raise RuntimeError("Race runtime is not initialized")
        return runtime

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        nonlocal runtime
        runtime = RaceRuntime.create(service_settings, database_path=database_path)
        app.state.runtime = runtime
        try:
            yield
        finally:
            if runtime is not None:
                runtime.shutdown()
                runtime = None
                app.state.runtime = None

    app = FastAPI(title="Tri Timing Local Service", lifespan=lifespan)

    @app.get("/api/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/race/state")
    async def race_state():
        return get_runtime().state()

    @app.post("/api/race/start")
    async def start_race():
        return get_runtime().start()

    @app.post("/api/race/close")
    async def close_race():
        return get_runtime().close()

    return app
