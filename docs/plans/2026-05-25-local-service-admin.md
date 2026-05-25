# Local Service And Admin UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a FastAPI local race-day service and a minimal React/Vite admin UI that drive the existing `tri_timing` core without hardware.

**Architecture:** `tri_timing` remains pure timing library code. `tri_timing_service` adapts it to HTTP/SSE and process runtime. `apps/admin` is a TypeScript React UI that calls service APIs and never owns race logic.

**Tech Stack:** Python 3.11+, `uv`, FastAPI, pytest, React, Vite, TypeScript, Vitest.

---

## File Structure

```text
apps/local-core/
  pyproject.toml
  src/tri_timing_service/
    __init__.py
    app.py
    broadcaster.py
    models.py
    runtime.py
    settings.py
  tests/
    test_service_api.py
    test_service_runtime.py

apps/admin/
  package.json
  index.html
  tsconfig.json
  vite.config.ts
  src/
    App.tsx
    api.ts
    main.tsx
    styles.css
    types.ts
    App.test.tsx
```

## Task 1: Add FastAPI Dependencies And Service Package

**Files:**
- Modify: `apps/local-core/pyproject.toml`
- Create: `apps/local-core/src/tri_timing_service/__init__.py`
- Create: `apps/local-core/src/tri_timing_service/settings.py`
- Test: `apps/local-core/tests/test_service_runtime.py`

- [ ] **Step 1: Add failing settings test**

Create `apps/local-core/tests/test_service_runtime.py`:

```python
from pathlib import Path

from tri_timing_service.settings import ServiceSettings


def test_service_settings_defaults_to_fixture_paths() -> None:
    settings = ServiceSettings.for_tests()

    assert settings.race_config_path == Path("tests/fixtures/race.yaml")
    assert settings.athletes_path == Path("tests/fixtures/athletes.csv")
    assert settings.database_path.name == "tri-timing-test.sqlite"
```

- [ ] **Step 2: Run failing test**

Run from `apps/local-core`:

```bash
uv run pytest tests/test_service_runtime.py -v
```

Expected: fail because `tri_timing_service` does not exist.

- [ ] **Step 3: Add dependencies and settings implementation**

Modify `apps/local-core/pyproject.toml` dependencies:

```toml
dependencies = [
  "pydantic>=2.7",
  "PyYAML>=6.0",
  "bleak>=0.22",
  "fastapi>=0.115",
  "httpx>=0.27",
  "uvicorn>=0.30",
]
```

Create `apps/local-core/src/tri_timing_service/__init__.py`:

```python
"""Local HTTP service for the tri timing core."""
```

Create `apps/local-core/src/tri_timing_service/settings.py`:

```python
from dataclasses import dataclass
from pathlib import Path
from tempfile import gettempdir


@dataclass(frozen=True)
class ServiceSettings:
    race_config_path: Path
    athletes_path: Path
    database_path: Path

    @classmethod
    def for_tests(cls) -> "ServiceSettings":
        return cls(
            race_config_path=Path("tests/fixtures/race.yaml"),
            athletes_path=Path("tests/fixtures/athletes.csv"),
            database_path=Path(gettempdir()) / "tri-timing-test.sqlite",
        )
```

- [ ] **Step 4: Verify test passes**

```bash
uv run pytest tests/test_service_runtime.py -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add apps/local-core/pyproject.toml apps/local-core/src/tri_timing_service apps/local-core/tests/test_service_runtime.py
git commit -m "feat: add local service package"
```

## Task 2: Add Runtime State Projection

**Files:**
- Create: `apps/local-core/src/tri_timing_service/models.py`
- Create: `apps/local-core/src/tri_timing_service/runtime.py`
- Modify: `apps/local-core/tests/test_service_runtime.py`

- [ ] **Step 1: Add failing runtime tests**

Append to `apps/local-core/tests/test_service_runtime.py`:

```python
from tri_timing_service.runtime import RaceRuntime


def test_runtime_starts_in_pre_start_phase(tmp_path) -> None:
    settings = ServiceSettings.for_tests()
    runtime = RaceRuntime.create(settings, database_path=tmp_path / "race.sqlite")

    state = runtime.state()

    assert state.phase == "pre_start"
    assert len(state.athletes) == 2
    assert state.athletes[0].next_event_id == "run1_lap1_complete"


def test_runtime_start_and_close_are_idempotent(tmp_path) -> None:
    settings = ServiceSettings.for_tests()
    runtime = RaceRuntime.create(settings, database_path=tmp_path / "race.sqlite")

    first = runtime.start()
    second = runtime.start()
    closed = runtime.close()
    closed_again = runtime.close()

    assert first.phase == "live"
    assert second.phase == "live"
    assert closed.phase == "closed"
    assert closed_again.phase == "closed"
```

- [ ] **Step 2: Run failing tests**

```bash
uv run pytest tests/test_service_runtime.py -v
```

Expected: fail because `RaceRuntime` does not exist.

- [ ] **Step 3: Add runtime models**

Create `apps/local-core/src/tri_timing_service/models.py`:

```python
from pydantic import BaseModel


class AthleteView(BaseModel):
    athlete_id: str
    name: str
    bib_number: str | None
    next_event_id: str | None
    status: str


class AcceptedEventView(BaseModel):
    athlete_id: str
    route_event_id: str
    checkpoint_id: str
    timestamp: str
    confidence: str


class RaceStateView(BaseModel):
    race_id: str
    phase: str
    athletes: list[AthleteView]
    accepted_events: list[AcceptedEventView]
    warnings: list[str]
```

- [ ] **Step 4: Add minimal runtime**

Create `apps/local-core/src/tri_timing_service/runtime.py`:

```python
from pathlib import Path

from tri_timing.config import load_athletes, load_race_config
from tri_timing.engine import RaceEngine
from tri_timing.route import compile_route
from tri_timing.store import EventStore
from tri_timing_service.models import AcceptedEventView, AthleteView, RaceStateView
from tri_timing_service.settings import ServiceSettings


class RaceRuntime:
    def __init__(self, settings: ServiceSettings, database_path: Path) -> None:
        self._settings = settings
        self._race_config = load_race_config(settings.race_config_path)
        self._athletes = load_athletes(settings.athletes_path)
        self._route = compile_route(self._race_config)
        self._store = EventStore(database_path)
        self._engine = RaceEngine(race_id=self._race_config.race_id, route_events=self._route)
        for athlete in self._athletes:
            self._engine.add_athlete(athlete.athlete_id)
        self._phase = "pre_start"

    @classmethod
    def create(cls, settings: ServiceSettings, database_path: Path | None = None) -> "RaceRuntime":
        return cls(settings, database_path or settings.database_path)

    def state(self) -> RaceStateView:
        athletes = []
        for athlete in self._athletes:
            engine_state = self._engine.state_for(athlete.athlete_id)
            next_event = (
                self._route[engine_state.next_route_event_index]
                if engine_state.next_route_event_index < len(self._route)
                else None
            )
            athletes.append(
                AthleteView(
                    athlete_id=athlete.athlete_id,
                    name=athlete.name,
                    bib_number=str(athlete.bib),
                    next_event_id=next_event.id if next_event else None,
                    status=engine_state.status,
                )
            )
        return RaceStateView(
            race_id=self._race_config.race_id,
            phase=self._phase,
            athletes=athletes,
            accepted_events=[
                AcceptedEventView(
                    athlete_id=row["athlete_id"],
                    route_event_id=row["route_event_id"],
                    checkpoint_id=row["checkpoint_id"],
                    timestamp=row["event_time_wall"],
                    confidence=row["confidence"],
                )
                for row in self._store.accepted_route_events()
            ],
            warnings=[],
        )

    def start(self) -> RaceStateView:
        if self._phase != "closed":
            self._phase = "live"
            self._engine.start(race_start_sec=100, start_grace_sec=self._race_config.start.start_grace_sec)
        return self.state()

    def close(self) -> RaceStateView:
        self._phase = "closed"
        return self.state()
```

- [ ] **Step 5: Verify runtime tests pass**

```bash
uv run pytest tests/test_service_runtime.py -v
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add apps/local-core/src/tri_timing_service apps/local-core/tests/test_service_runtime.py
git commit -m "feat: add local race runtime"
```

## Task 3: Add FastAPI App And Core Endpoints

**Files:**
- Create: `apps/local-core/src/tri_timing_service/app.py`
- Test: `apps/local-core/tests/test_service_api.py`

- [ ] **Step 1: Add failing API tests**

Create `apps/local-core/tests/test_service_api.py`:

```python
from fastapi.testclient import TestClient

from tri_timing_service.app import create_app
from tri_timing_service.settings import ServiceSettings


def test_health_endpoint(tmp_path) -> None:
    app = create_app(ServiceSettings.for_tests(), database_path=tmp_path / "race.sqlite")
    client = TestClient(app)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_state_start_and_close_endpoints(tmp_path) -> None:
    app = create_app(ServiceSettings.for_tests(), database_path=tmp_path / "race.sqlite")
    client = TestClient(app)

    initial = client.get("/api/race/state").json()
    started = client.post("/api/race/start").json()
    closed = client.post("/api/race/close").json()

    assert initial["phase"] == "pre_start"
    assert started["phase"] == "live"
    assert closed["phase"] == "closed"
```

- [ ] **Step 2: Run failing API tests**

```bash
uv run pytest tests/test_service_api.py -v
```

Expected: fail because `tri_timing_service.app` does not exist.

- [ ] **Step 3: Add FastAPI app**

Create `apps/local-core/src/tri_timing_service/app.py`:

```python
from pathlib import Path

from fastapi import FastAPI

from tri_timing_service.settings import ServiceSettings
from tri_timing_service.runtime import RaceRuntime


def create_app(settings: ServiceSettings | None = None, database_path: Path | None = None) -> FastAPI:
    runtime = RaceRuntime.create(settings or ServiceSettings.for_tests(), database_path=database_path)
    app = FastAPI(title="Tri Timing Local Service")

    @app.get("/api/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/race/state")
    def race_state():
        return runtime.state()

    @app.post("/api/race/start")
    def start_race():
        return runtime.start()

    @app.post("/api/race/close")
    def close_race():
        return runtime.close()

    return app
```

- [ ] **Step 4: Verify API tests pass**

```bash
uv run pytest tests/test_service_api.py -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add apps/local-core/src/tri_timing_service/app.py apps/local-core/tests/test_service_api.py
git commit -m "feat: expose local race service api"
```

## Task 4: Add Synthetic Detection Endpoint

**Files:**
- Modify: `apps/local-core/src/tri_timing_service/models.py`
- Modify: `apps/local-core/src/tri_timing_service/runtime.py`
- Modify: `apps/local-core/src/tri_timing_service/app.py`
- Modify: `apps/local-core/tests/test_service_api.py`

- [ ] **Step 1: Add failing synthetic endpoint test**

Append to `apps/local-core/tests/test_service_api.py`:

```python
def test_synthetic_detection_advances_expected_event(tmp_path) -> None:
    app = create_app(ServiceSettings.for_tests(), database_path=tmp_path / "race.sqlite")
    client = TestClient(app)
    client.post("/api/race/start")

    response = client.post(
        "/api/synthetic/detection",
        json={
            "athlete_id": "A001",
            "checkpoint_id": "gate",
            "receiver_id": "synthetic",
            "rssi": -55,
            "repeat_count": 6,
            "timestamp_sec": 500,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["accepted_events"][0]["route_event_id"] == "run1_lap1_complete"
    assert body["athletes"][0]["next_event_id"] == "run1_lap2_complete"
```

- [ ] **Step 2: Run failing test**

```bash
uv run pytest tests/test_service_api.py::test_synthetic_detection_advances_expected_event -v
```

Expected: fail because endpoint does not exist.

- [ ] **Step 3: Add request model**

Append to `apps/local-core/src/tri_timing_service/models.py`:

```python
class SyntheticDetectionRequest(BaseModel):
    athlete_id: str
    checkpoint_id: str
    receiver_id: str = "synthetic"
    rssi: int = -55
    repeat_count: int = 6
    timestamp_sec: float | None = None
```

- [ ] **Step 4: Add runtime ingestion method**

Add to `RaceRuntime` in `apps/local-core/src/tri_timing_service/runtime.py`:

```python
from datetime import UTC, datetime

from tri_timing.detector import PassDetector
from tri_timing_service.models import SyntheticDetectionRequest
```

Add method:

```python
    def synthetic_detection(self, request: SyntheticDetectionRequest) -> RaceStateView:
        if self._phase != "live":
            return self.state()

        engine_state = self._engine.state_for(request.athlete_id)
        if engine_state.next_route_event_index >= len(self._route):
            return self.state()

        expected_event = self._route[engine_state.next_route_event_index]
        policy = self._race_config.detection_policies[expected_event.detection_policy_id]
        detector = PassDetector(policy)
        timestamp_sec = request.timestamp_sec
        if timestamp_sec is None:
            baseline = engine_state.last_event_time_sec or self._engine.race_start_sec or 100
            timestamp_sec = baseline + expected_event.min_elapsed_sec + self._race_config.start.start_grace_sec + 1

        beacon = next(athlete for athlete in self._athletes if athlete.athlete_id == request.athlete_id)
        candidate = None
        wall_time = datetime.now(tz=UTC).isoformat()
        samples = [
            (timestamp_sec + index, request.rssi)
            for index in range(request.repeat_count)
        ]
        samples.append((timestamp_sec + request.repeat_count + policy.clear_sec, policy.close_rssi_threshold))

        for index, (sample_time, rssi) in enumerate(samples):
            self._store.append_raw_detection(
                race_id=self._race_config.race_id,
                receiver_id=request.receiver_id,
                checkpoint_id=request.checkpoint_id,
                beacon_uuid=beacon.beacon_uuid,
                beacon_major=beacon.beacon_major,
                beacon_minor=beacon.beacon_minor,
                rssi=rssi,
                timestamp_wall=wall_time,
                timestamp_monotonic=sample_time,
                process_instance_id="synthetic",
            )
            candidate = detector.observe(timestamp_sec=sample_time, rssi=rssi) or candidate

        if candidate is not None:
            decision = self._engine.apply_pass(request.athlete_id, request.checkpoint_id, candidate)
            if decision.status == "accepted" and decision.route_event_id is not None:
                self._store.append_accepted_route_event(
                    race_id=self._race_config.race_id,
                    athlete_id=request.athlete_id,
                    route_event_id=decision.route_event_id,
                    checkpoint_id=request.checkpoint_id,
                    pass_candidate_id=candidate.candidate_id,
                    event_time_wall=wall_time,
                    confidence=candidate.confidence,
                )
        return self.state()
```

- [ ] **Step 5: Add endpoint**

Modify `apps/local-core/src/tri_timing_service/app.py` imports:

```python
from tri_timing_service.models import SyntheticDetectionRequest
```

Add endpoint:

```python
    @app.post("/api/synthetic/detection")
    def synthetic_detection(request: SyntheticDetectionRequest):
        return runtime.synthetic_detection(request)
```

- [ ] **Step 6: Verify synthetic test passes**

```bash
uv run pytest tests/test_service_api.py::test_synthetic_detection_advances_expected_event -v
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add apps/local-core/src/tri_timing_service apps/local-core/tests/test_service_api.py
git commit -m "feat: add synthetic detection api"
```

## Task 5: Add SSE Broadcaster Skeleton

**Files:**
- Create: `apps/local-core/src/tri_timing_service/broadcaster.py`
- Modify: `apps/local-core/src/tri_timing_service/app.py`
- Modify: `apps/local-core/tests/test_service_api.py`

- [ ] **Step 1: Add failing SSE test**

Append to `apps/local-core/tests/test_service_api.py`:

```python
def test_sse_stream_opens(tmp_path) -> None:
    app = create_app(ServiceSettings.for_tests(), database_path=tmp_path / "race.sqlite")
    client = TestClient(app)

    with client.stream("GET", "/api/events/stream") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
```

- [ ] **Step 2: Run failing test**

```bash
uv run pytest tests/test_service_api.py::test_sse_stream_opens -v
```

Expected: fail because endpoint does not exist.

- [ ] **Step 3: Add simple broadcaster**

Create `apps/local-core/src/tri_timing_service/broadcaster.py`:

```python
from collections.abc import Iterator


class EventBroadcaster:
    def initial_stream(self) -> Iterator[str]:
        yield "event: connected\ndata: {}\n\n"
```

- [ ] **Step 4: Add SSE endpoint**

Modify `apps/local-core/src/tri_timing_service/app.py` imports:

```python
from fastapi.responses import StreamingResponse
from tri_timing_service.broadcaster import EventBroadcaster
```

Inside `create_app` before routes:

```python
    broadcaster = EventBroadcaster()
```

Add route:

```python
    @app.get("/api/events/stream")
    def event_stream():
        return StreamingResponse(broadcaster.initial_stream(), media_type="text/event-stream")
```

- [ ] **Step 5: Verify SSE test passes**

```bash
uv run pytest tests/test_service_api.py::test_sse_stream_opens -v
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add apps/local-core/src/tri_timing_service apps/local-core/tests/test_service_api.py
git commit -m "feat: add local event stream endpoint"
```

## Task 6: Scaffold React Admin App

**Files:**
- Create: `apps/admin/package.json`
- Create: `apps/admin/index.html`
- Create: `apps/admin/tsconfig.json`
- Create: `apps/admin/vite.config.ts`
- Create: `apps/admin/src/main.tsx`
- Create: `apps/admin/src/types.ts`
- Create: `apps/admin/src/api.ts`
- Create: `apps/admin/src/App.tsx`
- Create: `apps/admin/src/styles.css`
- Create: `apps/admin/src/App.test.tsx`

- [ ] **Step 1: Create package files**

Create `apps/admin/package.json`:

```json
{
  "name": "tri-timing-admin",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "test": "vitest run"
  },
  "dependencies": {
    "@vitejs/plugin-react": "^5.0.0",
    "vite": "^7.0.0",
    "typescript": "^5.8.0",
    "react": "^19.0.0",
    "react-dom": "^19.0.0"
  },
  "devDependencies": {
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "@testing-library/react": "^16.0.0",
    "@testing-library/jest-dom": "^6.0.0",
    "jsdom": "^25.0.0",
    "vitest": "^3.0.0"
  }
}
```

Create `apps/admin/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["DOM", "DOM.Iterable", "ES2022"],
    "allowJs": false,
    "skipLibCheck": true,
    "esModuleInterop": true,
    "allowSyntheticDefaultImports": true,
    "strict": true,
    "forceConsistentCasingInFileNames": true,
    "module": "ESNext",
    "moduleResolution": "Node",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx"
  },
  "include": ["src"]
}
```

Create `apps/admin/vite.config.ts`:

```ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
  },
});
```

Create `apps/admin/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Tri Timing Admin</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 2: Add app code**

Create `apps/admin/src/types.ts`:

```ts
export type AthleteView = {
  athlete_id: string;
  name: string;
  bib_number: string | null;
  next_event_id: string | null;
  status: string;
};

export type AcceptedEventView = {
  athlete_id: string;
  route_event_id: string;
  checkpoint_id: string;
  timestamp: string;
  confidence: string;
};

export type RaceStateView = {
  race_id: string;
  phase: string;
  athletes: AthleteView[];
  accepted_events: AcceptedEventView[];
  warnings: string[];
};
```

Create `apps/admin/src/api.ts`:

```ts
import type { RaceStateView } from "./types";

async function requestState(path: string, init?: RequestInit): Promise<RaceStateView> {
  const response = await fetch(path, {
    headers: { "content-type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
}

export function getRaceState(): Promise<RaceStateView> {
  return requestState("/api/race/state");
}

export function startRace(): Promise<RaceStateView> {
  return requestState("/api/race/start", { method: "POST" });
}

export function closeRace(): Promise<RaceStateView> {
  return requestState("/api/race/close", { method: "POST" });
}

export function sendSyntheticDetection(athleteId: string, checkpointId: string): Promise<RaceStateView> {
  return requestState("/api/synthetic/detection", {
    method: "POST",
    body: JSON.stringify({
      athlete_id: athleteId,
      checkpoint_id: checkpointId,
      receiver_id: "admin",
      rssi: -55,
      repeat_count: 6,
    }),
  });
}
```

Create `apps/admin/src/App.tsx`:

```tsx
import { useEffect, useState } from "react";
import { closeRace, getRaceState, sendSyntheticDetection, startRace } from "./api";
import type { RaceStateView } from "./types";
import "./styles.css";

export function App() {
  const [state, setState] = useState<RaceStateView | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getRaceState().then(setState).catch((err: Error) => setError(err.message));
  }, []);

  async function run(action: () => Promise<RaceStateView>) {
    setError(null);
    try {
      setState(await action());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  return (
    <main className="shell">
      <section className="hero">
        <p className="eyebrow">Local Race Authority</p>
        <h1>Tri Timing Admin</h1>
        <p>Phase: <strong>{state?.phase ?? "connecting"}</strong></p>
        {error ? <p role="alert">{error}</p> : null}
        <div className="controls">
          <button onClick={() => run(startRace)}>Start Race</button>
          <button onClick={() => run(closeRace)}>Close Race</button>
        </div>
      </section>

      <section className="panel">
        <h2>Athletes</h2>
        {state?.athletes.map((athlete) => (
          <article className="athlete" key={athlete.athlete_id}>
            <div>
              <strong>{athlete.name}</strong>
              <span>{athlete.next_event_id ?? "finished"}</span>
            </div>
            <button onClick={() => run(() => sendSyntheticDetection(athlete.athlete_id, "gate"))}>
              Synthetic Pass
            </button>
          </article>
        ))}
      </section>

      <section className="panel">
        <h2>Accepted Events</h2>
        {state?.accepted_events.length ? (
          state.accepted_events.map((event) => (
            <p key={`${event.athlete_id}-${event.route_event_id}`}>
              {event.athlete_id} · {event.route_event_id}
            </p>
          ))
        ) : (
          <p>No accepted events yet.</p>
        )}
      </section>
    </main>
  );
}
```

Create `apps/admin/src/main.tsx`:

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

Create `apps/admin/src/styles.css`:

```css
:root {
  color: #18211f;
  background: #f2eadb;
  font-family: "Avenir Next", "Gill Sans", sans-serif;
}

body {
  margin: 0;
}

button {
  border: 0;
  border-radius: 999px;
  background: #0e5f4f;
  color: white;
  cursor: pointer;
  padding: 0.75rem 1rem;
}

.shell {
  display: grid;
  gap: 1rem;
  margin: 0 auto;
  max-width: 960px;
  padding: 2rem;
}

.hero,
.panel {
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid rgba(24, 33, 31, 0.12);
  border-radius: 24px;
  padding: 1.5rem;
}

.eyebrow {
  color: #9a4b27;
  font-size: 0.8rem;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.controls,
.athlete {
  display: flex;
  gap: 1rem;
}

.athlete {
  align-items: center;
  justify-content: space-between;
}

.athlete span {
  color: #5d6863;
  display: block;
}
```

- [ ] **Step 3: Add render test**

Create `apps/admin/src/App.test.tsx`:

```tsx
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { App } from "./App";

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async () => ({
    ok: true,
    json: async () => ({
      race_id: "duathlon-001",
      phase: "pre_start",
      athletes: [
        {
          athlete_id: "A001",
          name: "Bob",
          bib_number: "1",
          next_event_id: "run1_lap1_complete",
          status: "racing",
        },
      ],
      accepted_events: [],
      warnings: [],
    }),
  })));
});

test("renders race state from api", async () => {
  render(<App />);

  expect(await screen.findByText("Bob")).toBeInTheDocument();
  expect(screen.getByText("run1_lap1_complete")).toBeInTheDocument();
});
```

- [ ] **Step 4: Install and test admin**

Run from `apps/admin`:

```bash
npm install
npm test
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add apps/admin
git commit -m "feat: add local admin shell"
```

## Task 7: Update Documentation

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `apps/local-core/README.md`

- [ ] **Step 1: Update root README planned/current status**

Add local service/admin commands:

```bash
cd apps/local-core
uv run uvicorn tri_timing_service.app:create_app --factory --reload

cd apps/admin
npm install
npm run dev
```

- [ ] **Step 2: Update AGENTS.md command list**

Add:

```text
Local service commands run from `apps/local-core`.
Admin UI commands run from `apps/admin`.
```

- [ ] **Step 3: Update local-core README**

Document:

```text
`tri_timing` is library code.
`tri_timing_service` is local FastAPI runtime adapter.
```

- [ ] **Step 4: Verify all tests**

Run:

```bash
cd apps/local-core
uv run pytest -v
```

Run:

```bash
cd apps/admin
npm test
npm run build
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add README.md AGENTS.md apps/local-core/README.md
git commit -m "docs: document local service and admin"
```

## Self-Review Checklist

- Spec coverage: service startup, state, start/close, synthetic detection, SSE skeleton, admin shell, docs all mapped to tasks.
- No hardware dependency: synthetic endpoint provides full no-hardware path.
- Core boundary preserved: route and timing logic remain in `tri_timing`.
- Known implementation risk: exact `RaceEngine` method names may need adjustment against current code during Task 2/4.
