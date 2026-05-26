import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from tri_timing_service.broadcaster import EventBroadcaster
from tri_timing_service.models import ManualCorrectionRequest, SyntheticDetectionRequest
from tri_timing_service.runtime import RaceRuntime
from tri_timing_service.settings import ServiceSettings


def create_app(
    settings: ServiceSettings | None = None,
    database_path: Path | None = None,
) -> FastAPI:
    service_settings = settings or ServiceSettings.from_env()
    broadcaster = EventBroadcaster()
    runtime: RaceRuntime | None = None
    sync_task: asyncio.Task[None] | None = None

    def get_runtime() -> RaceRuntime:
        if runtime is None:
            raise RuntimeError("Race runtime is not initialized")
        return runtime

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        nonlocal runtime, sync_task
        runtime = RaceRuntime.create(service_settings, database_path=database_path)
        app.state.runtime = runtime
        sync_task = asyncio.create_task(_cloud_sync_loop())
        try:
            yield
        finally:
            if sync_task is not None:
                sync_task.cancel()
                try:
                    await sync_task
                except asyncio.CancelledError:
                    pass
                sync_task = None
            if runtime is not None:
                runtime.shutdown()
                runtime = None
                app.state.runtime = None

    app = FastAPI(title="Tri Timing Local Service", lifespan=lifespan)

    async def _cloud_sync_loop() -> None:
        while True:
            await asyncio.sleep(service_settings.cloud_sync_interval_sec)
            current_runtime = runtime
            if current_runtime is not None:
                await current_runtime.publish_cloud_sync_once()

    @app.get("/api/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/events/stream")
    async def event_stream():
        return StreamingResponse(
            broadcaster.stream(get_runtime().state()),
            media_type="text/event-stream",
        )

    @app.get("/api/race/state")
    async def race_state():
        return get_runtime().state()

    @app.get("/api/review/state")
    async def review_state():
        return get_runtime().review_state()

    @app.get("/api/corrections")
    async def corrections():
        return {"corrections": get_runtime().corrections()}

    @app.post("/api/race/start")
    async def start_race():
        state = get_runtime().start()
        broadcaster.publish_state(state)
        return state

    @app.post("/api/race/close")
    async def close_race():
        state = get_runtime().close()
        broadcaster.publish_state(state)
        return state

    @app.post("/api/synthetic/detection")
    async def synthetic_detection(request: SyntheticDetectionRequest):
        try:
            state = get_runtime().synthetic_detection(request)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        broadcaster.publish_state(state)
        return state

    @app.post("/api/corrections")
    async def create_correction(request: ManualCorrectionRequest):
        current_runtime = get_runtime()
        try:
            review = current_runtime.apply_manual_correction(request)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        broadcaster.publish_review(review)
        broadcaster.publish_state(current_runtime.state())
        return review

    return app
