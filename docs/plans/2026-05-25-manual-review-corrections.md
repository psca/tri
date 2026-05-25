# Manual Review And Corrections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add append-only manual correction facts, corrected review projection, local correction APIs, and a fast operator review UI.

**Architecture:** `EventStore` persists correction facts and sync outbox payloads. A new review projection module derives corrected timelines from route config, accepted events, and corrections. FastAPI exposes review/correction endpoints; React admin adds a review mode optimized for quick race-day fixes.

**Tech Stack:** Python 3.11+, `uv`, SQLite, FastAPI, pytest, React, TypeScript, Vite, Vitest.

---

## File Structure

```text
apps/local-core/
  src/tri_timing/store.py
  src/tri_timing/review.py
  src/tri_timing_service/models.py
  src/tri_timing_service/runtime.py
  src/tri_timing_service/app.py
  tests/test_store.py
  tests/test_review_projection.py
  tests/test_service_api.py

apps/admin/
  src/api.ts
  src/types.ts
  src/App.tsx
  src/App.test.tsx
  src/styles.css

docs/acceptance/manual-review-corrections.md
README.md
AGENTS.md
```

## Task 1: Store Manual Corrections

**Files:**
- Modify: `apps/local-core/src/tri_timing/store.py`
- Modify: `apps/local-core/tests/test_store.py`

- [ ] **Step 1: Add failing store tests**

Append to `apps/local-core/tests/test_store.py`:

```python
def test_append_manual_correction_persists_fact_and_sync_payload(tmp_path) -> None:
    store = EventStore(tmp_path / "race.sqlite")

    sequence = store.append_manual_correction(
        race_id="duathlon-demo",
        correction_type="manual_add_pass",
        athlete_id="A001",
        route_event_id="run1_lap1_complete",
        target_local_sequence_number=None,
        corrected_time_wall="2026-05-25T09:10:00+08:00",
        status=None,
        reason="Saw athlete cross while BLE missed",
        created_at="2026-05-25T09:11:00+08:00",
        created_by="operator",
    )

    corrections = store.manual_corrections()
    assert corrections[0]["local_sequence_number"] == sequence
    assert corrections[0]["correction_type"] == "manual_add_pass"
    assert corrections[0]["reason"] == "Saw athlete cross while BLE missed"

    outbox = store.sync_outbox()
    assert outbox[0]["local_sequence_number"] == sequence
    assert outbox[0]["status"] == "pending"
    assert '"type": "manual_correction"' in outbox[0]["payload_json"]


def test_manual_corrections_are_ordered_by_sequence(tmp_path) -> None:
    store = EventStore(tmp_path / "race.sqlite")
    first = store.append_manual_correction(
        race_id="duathlon-demo",
        correction_type="mark_status",
        athlete_id="A001",
        route_event_id=None,
        target_local_sequence_number=None,
        corrected_time_wall=None,
        status="dnf",
        reason="Stopped after bike",
        created_at="2026-05-25T10:00:00+08:00",
        created_by="operator",
    )
    second = store.append_manual_correction(
        race_id="duathlon-demo",
        correction_type="mark_status",
        athlete_id="A002",
        route_event_id=None,
        target_local_sequence_number=None,
        corrected_time_wall=None,
        status="dq",
        reason="Wrong course",
        created_at="2026-05-25T10:01:00+08:00",
        created_by="operator",
    )

    assert [row["local_sequence_number"] for row in store.manual_corrections()] == [
        first,
        second,
    ]
```

- [ ] **Step 2: Run failing tests**

```bash
cd apps/local-core
uv run pytest tests/test_store.py::test_append_manual_correction_persists_fact_and_sync_payload tests/test_store.py::test_manual_corrections_are_ordered_by_sequence -v
```

Expected: fail because `append_manual_correction` and `manual_corrections` do not exist.

- [ ] **Step 3: Add table and methods**

Modify `_migrate()` in `apps/local-core/src/tri_timing/store.py` to create:

```sql
CREATE TABLE IF NOT EXISTS manual_corrections (
  local_sequence_number INTEGER PRIMARY KEY,
  race_id TEXT NOT NULL,
  correction_type TEXT NOT NULL,
  athlete_id TEXT NOT NULL,
  route_event_id TEXT,
  target_local_sequence_number INTEGER,
  corrected_time_wall TEXT,
  status TEXT,
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL,
  created_by TEXT NOT NULL
);
```

Add methods:

```python
def append_manual_correction(
    self,
    *,
    race_id: str,
    correction_type: str,
    athlete_id: str,
    route_event_id: str | None,
    target_local_sequence_number: int | None,
    corrected_time_wall: str | None,
    status: str | None,
    reason: str,
    created_at: str,
    created_by: str,
) -> int:
    with self.conn:
        sequence = self._next_sequence()
        self.conn.execute(
            """
            INSERT INTO manual_corrections (
              local_sequence_number, race_id, correction_type, athlete_id,
              route_event_id, target_local_sequence_number, corrected_time_wall,
              status, reason, created_at, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sequence,
                race_id,
                correction_type,
                athlete_id,
                route_event_id,
                target_local_sequence_number,
                corrected_time_wall,
                status,
                reason,
                created_at,
                created_by,
            ),
        )
        payload = {
            "type": "manual_correction",
            "local_sequence_number": sequence,
            "race_id": race_id,
            "correction_type": correction_type,
            "athlete_id": athlete_id,
            "route_event_id": route_event_id,
            "target_local_sequence_number": target_local_sequence_number,
            "corrected_time_wall": corrected_time_wall,
            "status": status,
            "reason": reason,
            "created_at": created_at,
            "created_by": created_by,
        }
        payload_json = json.dumps(payload, sort_keys=True)
        self.conn.execute(
            """
            INSERT INTO sync_outbox (
              local_sequence_number, idempotency_key, payload_hash, payload_json, status
            ) VALUES (?, ?, ?, ?, 'pending')
            """,
            (
                sequence,
                f"{race_id}:{sequence}",
                hashlib.sha256(payload_json.encode("utf-8")).hexdigest(),
                payload_json,
            ),
        )
        return sequence


def manual_corrections(self) -> list[dict[str, Any]]:
    rows = self.conn.execute(
        "SELECT * FROM manual_corrections ORDER BY local_sequence_number"
    ).fetchall()
    return [dict(row) for row in rows]
```

- [ ] **Step 4: Verify tests pass**

```bash
cd apps/local-core
uv run pytest tests/test_store.py -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add apps/local-core/src/tri_timing/store.py apps/local-core/tests/test_store.py
git commit -m "feat: store manual corrections"
```

## Task 2: Add Review Projection

**Files:**
- Create: `apps/local-core/src/tri_timing/review.py`
- Create: `apps/local-core/tests/test_review_projection.py`

- [ ] **Step 1: Add projection tests**

Create `apps/local-core/tests/test_review_projection.py`:

```python
from tri_timing.models import RouteEvent, RouteEventKind
from tri_timing.review import build_review_state


ROUTE = [
    RouteEvent(
        index=0,
        id="run1_lap1_complete",
        label="Run 1 Lap 1",
        checkpoint_id="gate",
        kind=RouteEventKind.LAP,
        sport="run",
        min_elapsed_sec=0,
        cooldown_sec=45,
        detection_policy_id="normal",
    ),
    RouteEvent(
        index=1,
        id="finish",
        label="Finish",
        checkpoint_id="gate",
        kind=RouteEventKind.FINISH,
        sport="run",
        min_elapsed_sec=0,
        cooldown_sec=45,
        detection_policy_id="strict",
    ),
]

ATHLETES = [
    {"athlete_id": "A001", "name": "Bob", "bib": 12},
    {"athlete_id": "A002", "name": "Mei", "bib": 7},
]


def test_review_projection_marks_missing_and_accepted_events() -> None:
    review = build_review_state(
        race_id="duathlon-demo",
        phase="live",
        athletes=ATHLETES,
        route_events=ROUTE,
        accepted_events=[
            {
                "local_sequence_number": 5,
                "race_id": "duathlon-demo",
                "athlete_id": "A001",
                "route_event_id": "run1_lap1_complete",
                "checkpoint_id": "gate",
                "event_time_wall": "2026-05-25T09:10:00+08:00",
                "confidence": "high",
            }
        ],
        manual_corrections=[],
        raw_detections=[],
    )

    bob = review.athletes[0]
    mei = review.athletes[1]
    assert bob.timeline[0].status == "accepted"
    assert bob.timeline[1].status == "missing"
    assert mei.attention_level == "needs_attention"


def test_review_projection_applies_manual_add_reject_override_and_status() -> None:
    review = build_review_state(
        race_id="duathlon-demo",
        phase="live",
        athletes=ATHLETES,
        route_events=ROUTE,
        accepted_events=[
            {
                "local_sequence_number": 5,
                "race_id": "duathlon-demo",
                "athlete_id": "A001",
                "route_event_id": "run1_lap1_complete",
                "checkpoint_id": "gate",
                "event_time_wall": "2026-05-25T09:10:00+08:00",
                "confidence": "high",
            }
        ],
        manual_corrections=[
            {
                "local_sequence_number": 6,
                "correction_type": "manual_reject_pass",
                "athlete_id": "A001",
                "target_local_sequence_number": 5,
                "route_event_id": None,
                "corrected_time_wall": None,
                "status": None,
                "reason": "False positive",
                "created_at": "2026-05-25T09:11:00+08:00",
                "created_by": "operator",
            },
            {
                "local_sequence_number": 7,
                "correction_type": "manual_add_pass",
                "athlete_id": "A001",
                "target_local_sequence_number": None,
                "route_event_id": "finish",
                "corrected_time_wall": "2026-05-25T09:40:00+08:00",
                "status": None,
                "reason": "Saw finish",
                "created_at": "2026-05-25T09:41:00+08:00",
                "created_by": "operator",
            },
            {
                "local_sequence_number": 8,
                "correction_type": "mark_status",
                "athlete_id": "A001",
                "target_local_sequence_number": None,
                "route_event_id": None,
                "corrected_time_wall": None,
                "status": "manual_finished",
                "reason": "Manual finish accepted",
                "created_at": "2026-05-25T09:42:00+08:00",
                "created_by": "operator",
            },
        ],
        raw_detections=[],
    )

    bob = review.athletes[0]
    assert bob.status == "manual_finished"
    assert bob.timeline[0].status == "rejected"
    assert bob.timeline[1].status == "manual"
    assert bob.timeline[1].source == "manual"
```

- [ ] **Step 2: Run failing tests**

```bash
cd apps/local-core
uv run pytest tests/test_review_projection.py -v
```

Expected: fail because `tri_timing.review` does not exist.

- [ ] **Step 3: Implement projection models and builder**

Create `apps/local-core/src/tri_timing/review.py` with Pydantic models:

```python
from __future__ import annotations

from pydantic import BaseModel

from tri_timing.models import RouteEvent


class ReviewTimelineEvent(BaseModel):
    route_event_id: str
    label: str
    status: str
    timestamp: str | None
    confidence: str | None
    source: str
    accepted_local_sequence_number: int | None = None
    original_timestamp: str | None = None
    correction_sequence_numbers: list[int] = []


class ReviewAthlete(BaseModel):
    athlete_id: str
    name: str
    bib_number: str | None
    status: str
    next_event_id: str | None
    completed_count: int
    total_count: int
    attention_level: str
    badges: list[str]
    timeline: list[ReviewTimelineEvent]


class ReviewState(BaseModel):
    race_id: str
    phase: str
    route_events: list[dict[str, str | int | None]]
    athletes: list[ReviewAthlete]
    correction_log: list[dict]
    warnings: list[str]
    raw_detections: list[dict]
```

Add `build_review_state(...)`:

```python
def build_review_state(
    *,
    race_id: str,
    phase: str,
    athletes: list[dict],
    route_events: list[RouteEvent],
    accepted_events: list[dict],
    manual_corrections: list[dict],
    raw_detections: list[dict],
) -> ReviewState:
    warnings: list[str] = []
    accepted_by_athlete_event = {
        (row["athlete_id"], row["route_event_id"]): row
        for row in accepted_events
        if row.get("race_id", race_id) == race_id
    }
    rejected_sequences: set[int] = set()
    manual_events: dict[tuple[str, str], dict] = {}
    override_times: dict[int, dict] = {}
    status_by_athlete: dict[str, str] = {}

    for correction in manual_corrections:
        ctype = correction["correction_type"]
        if ctype == "manual_reject_pass" and correction.get("target_local_sequence_number") is not None:
            rejected_sequences.add(int(correction["target_local_sequence_number"]))
        elif ctype == "manual_add_pass" and correction.get("route_event_id"):
            manual_events[(correction["athlete_id"], correction["route_event_id"])] = correction
        elif ctype == "manual_override_time" and correction.get("target_local_sequence_number") is not None:
            override_times[int(correction["target_local_sequence_number"])] = correction
        elif ctype == "mark_status" and correction.get("status"):
            status_by_athlete[correction["athlete_id"]] = correction["status"]
        else:
            warnings.append(f"ignored correction {correction.get('local_sequence_number')}: {ctype}")

    review_athletes: list[ReviewAthlete] = []
    for athlete in athletes:
        timeline: list[ReviewTimelineEvent] = []
        badges: set[str] = set()
        completed = 0
        next_event_id: str | None = None
        for route_event in route_events:
            key = (athlete["athlete_id"], route_event.id)
            accepted = accepted_by_athlete_event.get(key)
            manual = manual_events.get(key)
            if accepted:
                seq = int(accepted["local_sequence_number"])
                status = "rejected" if seq in rejected_sequences else "accepted"
                timestamp = accepted["event_time_wall"]
                original_timestamp = None
                source = "ble"
                if seq in override_times:
                    original_timestamp = timestamp
                    timestamp = override_times[seq]["corrected_time_wall"]
                    status = "overridden"
                    source = "override"
                    badges.add("overridden")
                if status == "rejected":
                    badges.add("rejected")
                else:
                    completed += 1
                timeline.append(
                    ReviewTimelineEvent(
                        route_event_id=route_event.id,
                        label=route_event.label,
                        status=status,
                        timestamp=timestamp,
                        confidence=accepted["confidence"],
                        source=source,
                        accepted_local_sequence_number=seq,
                        original_timestamp=original_timestamp,
                    )
                )
            elif manual:
                completed += 1
                badges.add("manual")
                timeline.append(
                    ReviewTimelineEvent(
                        route_event_id=route_event.id,
                        label=route_event.label,
                        status="manual",
                        timestamp=manual["corrected_time_wall"],
                        confidence=None,
                        source="manual",
                        correction_sequence_numbers=[manual["local_sequence_number"]],
                    )
                )
            else:
                if next_event_id is None:
                    next_event_id = route_event.id
                badges.add("missing")
                timeline.append(
                    ReviewTimelineEvent(
                        route_event_id=route_event.id,
                        label=route_event.label,
                        status="missing",
                        timestamp=None,
                        confidence=None,
                        source="none",
                    )
                )

        status = status_by_athlete.get(athlete["athlete_id"], "racing")
        attention = "needs_attention" if "missing" in badges or "rejected" in badges else "ok"
        review_athletes.append(
            ReviewAthlete(
                athlete_id=athlete["athlete_id"],
                name=athlete["name"],
                bib_number=str(athlete.get("bib")) if athlete.get("bib") is not None else None,
                status=status,
                next_event_id=next_event_id,
                completed_count=completed,
                total_count=len(route_events),
                attention_level=attention,
                badges=sorted(badges),
                timeline=timeline,
            )
        )

    review_athletes.sort(key=lambda athlete: (athlete.attention_level != "needs_attention", athlete.name))
    return ReviewState(
        race_id=race_id,
        phase=phase,
        route_events=[
            {
                "index": event.index,
                "id": event.id,
                "label": event.label,
                "checkpoint_id": event.checkpoint_id,
                "kind": event.kind,
                "sport": event.sport,
            }
            for event in route_events
        ],
        athletes=review_athletes,
        correction_log=manual_corrections,
        warnings=warnings,
        raw_detections=raw_detections,
    )
```

- [ ] **Step 4: Verify tests pass**

```bash
cd apps/local-core
uv run pytest tests/test_review_projection.py -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add apps/local-core/src/tri_timing/review.py apps/local-core/tests/test_review_projection.py
git commit -m "feat: add review projection"
```

## Task 3: Add Local Review And Correction API

**Files:**
- Modify: `apps/local-core/src/tri_timing_service/models.py`
- Modify: `apps/local-core/src/tri_timing_service/runtime.py`
- Modify: `apps/local-core/src/tri_timing_service/app.py`
- Modify: `apps/local-core/tests/test_service_api.py`

- [ ] **Step 1: Add failing API tests**

Append to `apps/local-core/tests/test_service_api.py`:

```python
def test_review_state_endpoint_returns_timelines(tmp_path) -> None:
    app = create_app(ServiceSettings.for_tests(), database_path=tmp_path / "race.sqlite")

    with TestClient(app) as client:
        response = client.get("/api/review/state")

    assert response.status_code == 200
    body = response.json()
    assert body["race_id"] == "duathlon-demo"
    assert body["athletes"][0]["timeline"]


def test_post_correction_adds_manual_pass_and_publishes_state(tmp_path) -> None:
    app = create_app(ServiceSettings.for_tests(), database_path=tmp_path / "race.sqlite")

    with TestClient(app) as client:
        response = client.post(
            "/api/corrections",
            json={
                "correction_type": "manual_add_pass",
                "athlete_id": "A001",
                "route_event_id": "run1_lap1_complete",
                "corrected_time_wall": "2026-05-25T09:10:00+08:00",
                "reason": "Saw athlete cross while BLE missed",
                "created_by": "operator",
            },
        )
        review = client.get("/api/review/state").json()

    assert response.status_code == 200
    assert review["athletes"][0]["timeline"][0]["status"] == "manual"


def test_post_correction_rejects_unknown_athlete(tmp_path) -> None:
    app = create_app(ServiceSettings.for_tests(), database_path=tmp_path / "race.sqlite")

    with TestClient(app) as client:
        response = client.post(
            "/api/corrections",
            json={
                "correction_type": "mark_status",
                "athlete_id": "UNKNOWN",
                "status": "dnf",
                "reason": "No such athlete",
                "created_by": "operator",
            },
        )

    assert response.status_code == 400
```

- [ ] **Step 2: Run failing API tests**

```bash
cd apps/local-core
uv run pytest tests/test_service_api.py::test_review_state_endpoint_returns_timelines tests/test_service_api.py::test_post_correction_adds_manual_pass_and_publishes_state tests/test_service_api.py::test_post_correction_rejects_unknown_athlete -v
```

Expected: fail because review/correction endpoints do not exist.

- [ ] **Step 3: Add request model**

Append to `apps/local-core/src/tri_timing_service/models.py`:

```python
class ManualCorrectionRequest(BaseModel):
    correction_type: str
    athlete_id: str
    route_event_id: str | None = None
    target_local_sequence_number: int | None = None
    corrected_time_wall: str | None = None
    status: str | None = None
    reason: str
    created_by: str = "operator"
```

- [ ] **Step 4: Add runtime methods**

Modify `apps/local-core/src/tri_timing_service/runtime.py`:

```python
from datetime import UTC, datetime
from tri_timing.review import ReviewState, build_review_state
from tri_timing_service.models import ManualCorrectionRequest
```

Add:

```python
def review_state(self) -> ReviewState:
    return build_review_state(
        race_id=self._race_config.race_id,
        phase=self._phase,
        athletes=[
            {"athlete_id": athlete.athlete_id, "name": athlete.name, "bib": athlete.bib}
            for athlete in self._athletes
        ],
        route_events=self._route,
        accepted_events=self._store.accepted_route_events(),
        manual_corrections=self._store.manual_corrections(),
        raw_detections=self._store.raw_detections(limit=25),
    )

def corrections(self) -> list[dict]:
    return self._store.manual_corrections()

def apply_manual_correction(self, request: ManualCorrectionRequest) -> ReviewState:
    athlete_ids = {athlete.athlete_id for athlete in self._athletes}
    route_event_ids = {event.id for event in self._route}
    if request.athlete_id not in athlete_ids:
        raise ValueError(f"unknown athlete: {request.athlete_id}")
    if request.route_event_id is not None and request.route_event_id not in route_event_ids:
        raise ValueError(f"unknown route event: {request.route_event_id}")
    if request.correction_type in {"manual_reject_pass", "manual_override_time"}:
        accepted_sequences = {
            row["local_sequence_number"] for row in self._store.accepted_route_events()
        }
        if request.target_local_sequence_number not in accepted_sequences:
            raise ValueError("target event does not exist")
    if not request.reason.strip():
        raise ValueError("reason is required")

    self._store.append_manual_correction(
        race_id=self._race_config.race_id,
        correction_type=request.correction_type,
        athlete_id=request.athlete_id,
        route_event_id=request.route_event_id,
        target_local_sequence_number=request.target_local_sequence_number,
        corrected_time_wall=request.corrected_time_wall,
        status=request.status,
        reason=request.reason,
        created_at=datetime.now(tz=UTC).isoformat(),
        created_by=request.created_by,
    )
    return self.review_state()
```

- [ ] **Step 5: Add FastAPI endpoints**

Modify `apps/local-core/src/tri_timing_service/app.py` imports:

```python
from tri_timing_service.models import ManualCorrectionRequest, SyntheticDetectionRequest
```

Add endpoints:

```python
@app.get("/api/review/state")
async def review_state():
    return get_runtime().review_state()

@app.get("/api/corrections")
async def corrections():
    return {"corrections": get_runtime().corrections()}

@app.post("/api/corrections")
async def create_correction(request: ManualCorrectionRequest):
    try:
        state = get_runtime().apply_manual_correction(request)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    broadcaster.publish_state(get_runtime().state())
    return state
```

- [ ] **Step 6: Verify API tests pass**

```bash
cd apps/local-core
uv run pytest tests/test_service_api.py -v
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add apps/local-core/src/tri_timing_service apps/local-core/tests/test_service_api.py
git commit -m "feat: expose manual correction api"
```

## Task 4: Add Admin Review Types And API Client

**Files:**
- Modify: `apps/admin/src/types.ts`
- Modify: `apps/admin/src/api.ts`
- Modify: `apps/admin/src/App.test.tsx`

- [ ] **Step 1: Add failing API test**

Append to `apps/admin/src/App.test.tsx` or create focused tests if current file is large:

```tsx
import { submitCorrection } from "./api";

test("submitCorrection posts correction payload", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
    new Response(JSON.stringify({ race_id: "duathlon-demo", phase: "live", athletes: [], route_events: [], correction_log: [], warnings: [], raw_detections: [] }), {
      status: 200,
      headers: { "content-type": "application/json" },
    }),
  );

  await submitCorrection({
    correction_type: "manual_add_pass",
    athlete_id: "A001",
    route_event_id: "run1_lap1_complete",
    corrected_time_wall: "2026-05-25T09:10:00+08:00",
    reason: "Saw athlete cross",
    created_by: "operator",
  });

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/corrections",
    expect.objectContaining({ method: "POST" }),
  );
  fetchMock.mockRestore();
});
```

- [ ] **Step 2: Run failing test**

```bash
cd apps/admin
npm test -- --run
```

Expected: fail because `submitCorrection` and review types do not exist.

- [ ] **Step 3: Add TypeScript review types**

Append to `apps/admin/src/types.ts`:

```ts
export type ReviewTimelineEvent = {
  route_event_id: string;
  label: string;
  status: "pending" | "accepted" | "missing" | "manual" | "overridden" | "rejected";
  timestamp: string | null;
  confidence: string | null;
  source: "ble" | "manual" | "override" | "none";
  accepted_local_sequence_number?: number | null;
  original_timestamp?: string | null;
  correction_sequence_numbers?: number[];
};

export type ReviewAthlete = {
  athlete_id: string;
  name: string;
  bib_number: string | null;
  status: string;
  next_event_id: string | null;
  completed_count: number;
  total_count: number;
  attention_level: "needs_attention" | "ok";
  badges: string[];
  timeline: ReviewTimelineEvent[];
};

export type ReviewState = {
  race_id: string;
  phase: string;
  route_events: Array<{ id: string; label: string; index: number }>;
  athletes: ReviewAthlete[];
  correction_log: Record<string, unknown>[];
  warnings: string[];
  raw_detections: RawDetectionView[];
};

export type ManualCorrectionRequest = {
  correction_type: "manual_add_pass" | "manual_reject_pass" | "manual_override_time" | "mark_status";
  athlete_id: string;
  route_event_id?: string | null;
  target_local_sequence_number?: number | null;
  corrected_time_wall?: string | null;
  status?: string | null;
  reason: string;
  created_by: string;
};
```

- [ ] **Step 4: Add API functions**

Modify `apps/admin/src/api.ts`:

```ts
import type { ManualCorrectionRequest, RaceStateView, ReviewState } from "./types";
```

Add:

```ts
async function requestReview(path: string, init?: RequestInit): Promise<ReviewState> {
  const response = await fetch(path, {
    headers: { "content-type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
}

export function getReviewState(): Promise<ReviewState> {
  return requestReview("/api/review/state");
}

export function submitCorrection(payload: ManualCorrectionRequest): Promise<ReviewState> {
  return requestReview("/api/corrections", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
```

- [ ] **Step 5: Verify admin tests pass**

```bash
cd apps/admin
npm test -- --run
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add apps/admin/src/types.ts apps/admin/src/api.ts apps/admin/src/App.test.tsx
git commit -m "feat: add admin review api client"
```

## Task 5: Build Review UI

**Files:**
- Modify: `apps/admin/src/App.tsx`
- Modify: `apps/admin/src/styles.css`
- Modify: `apps/admin/src/App.test.tsx`

- [ ] **Step 1: Add UI tests**

Append to `apps/admin/src/App.test.tsx`:

```tsx
test("review mode renders athlete timeline and correction actions", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url.includes("/api/race/state")) {
      return new Response(JSON.stringify({ race_id: "duathlon-demo", phase: "live", athletes: [], accepted_events: [], raw_detections: [], warnings: [] }), { status: 200 });
    }
    if (url.includes("/api/review/state")) {
      return new Response(JSON.stringify({
        race_id: "duathlon-demo",
        phase: "live",
        route_events: [{ id: "run1_lap1_complete", label: "Run 1 Lap 1", index: 0 }],
        athletes: [{
          athlete_id: "A001",
          name: "Bob",
          bib_number: "12",
          status: "racing",
          next_event_id: "run1_lap1_complete",
          completed_count: 0,
          total_count: 1,
          attention_level: "needs_attention",
          badges: ["missing"],
          timeline: [{ route_event_id: "run1_lap1_complete", label: "Run 1 Lap 1", status: "missing", timestamp: null, confidence: null, source: "none" }],
        }],
        correction_log: [],
        warnings: [],
        raw_detections: [],
      }), { status: 200 });
    }
    return new Response("{}", { status: 200 });
  });

  render(<App />);
  expect(await screen.findByText("Review")).toBeInTheDocument();
  await userEvent.click(screen.getByText("Review"));

  expect(await screen.findByText("Bob")).toBeInTheDocument();
  expect(screen.getByText("Run 1 Lap 1")).toBeInTheDocument();
  expect(screen.getByText("Add missing pass")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run failing tests**

```bash
cd apps/admin
npm test -- --run
```

Expected: fail because review mode does not exist.

- [ ] **Step 3: Add review state and mode**

Modify `apps/admin/src/App.tsx`:

- Import `getReviewState`, `submitCorrection`.
- Import `ReviewState`, `ReviewAthlete`, `ReviewTimelineEvent`.
- Add `mode` state with `"live" | "review"`.
- Fetch review state on mount and after correction.
- Render two top buttons: `Live` and `Review`.

Core implementation shape:

```tsx
const [mode, setMode] = useState<"live" | "review">("live");
const [review, setReview] = useState<ReviewState | null>(null);
const [selectedAthleteId, setSelectedAthleteId] = useState<string | null>(null);
const selectedAthlete = review?.athletes.find((athlete) => athlete.athlete_id === selectedAthleteId) ?? review?.athletes[0] ?? null;

async function refreshReview() {
  const next = await getReviewState();
  setReview(next);
  setSelectedAthleteId((current) => current ?? next.athletes[0]?.athlete_id ?? null);
}
```

Render review UI:

```tsx
{mode === "review" ? (
  <section className="review-layout">
    <aside className="review-list">
      {review?.athletes.map((athlete) => (
        <button className={`review-card ${athlete.attention_level}`} onClick={() => setSelectedAthleteId(athlete.athlete_id)} key={athlete.athlete_id}>
          <strong>{athlete.name}</strong>
          <span>{athlete.completed_count}/{athlete.total_count}</span>
          <span>{athlete.badges.join(", ") || "ok"}</span>
        </button>
      ))}
    </aside>
    <section className="timeline-panel">
      {selectedAthlete?.timeline.map((event) => (
        <article className={`timeline-event ${event.status}`} key={event.route_event_id}>
          <strong>{event.label}</strong>
          <span>{event.status}</span>
          <span>{event.timestamp ?? "No time"}</span>
        </article>
      ))}
    </section>
    <CorrectionPanel athlete={selectedAthlete} onSubmit={async (payload) => {
      await submitCorrection(payload);
      await refreshReview();
    }} />
  </section>
) : (
  existing live dashboard
)}
```

Implement `CorrectionPanel` in same file for MVP:

- Selected athlete required.
- Action selector.
- Event selector from selected athlete timeline.
- Time input defaults to current local ISO-like text.
- Reason input required.
- Confirm checkbox or confirmation button state before submit.

- [ ] **Step 4: Add review CSS**

Modify `apps/admin/src/styles.css` with classes:

```css
.mode-tabs {
  display: flex;
  gap: 0.75rem;
  margin-top: 1rem;
}

.review-layout {
  display: grid;
  grid-template-columns: minmax(220px, 0.85fr) minmax(340px, 1.4fr) minmax(260px, 1fr);
  gap: 1rem;
}

.review-card,
.timeline-event,
.correction-panel {
  border: 1px solid var(--line);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.72);
  padding: 1rem;
}

.review-card.needs_attention {
  border-color: #e3492d;
}

.timeline-event.manual,
.timeline-event.overridden {
  border-color: #e2a21a;
}

.timeline-event.rejected,
.timeline-event.missing {
  border-color: #e3492d;
}

@media (max-width: 900px) {
  .review-layout {
    grid-template-columns: 1fr;
  }
}
```

- [ ] **Step 5: Verify admin tests and build**

```bash
cd apps/admin
npm test -- --run
npm run build
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add apps/admin/src/App.tsx apps/admin/src/styles.css apps/admin/src/App.test.tsx
git commit -m "feat: add manual review admin ui"
```

## Task 6: Documentation And Full Verification

**Files:**
- Create: `docs/acceptance/manual-review-corrections.md`
- Modify: `README.md`
- Modify: `AGENTS.md`

- [ ] **Step 1: Add acceptance checklist**

Create `docs/acceptance/manual-review-corrections.md`:

```markdown
# Manual Review And Corrections Acceptance Checklist

- [ ] Operator can open Review mode during a live race.
- [ ] Review state shows athlete timelines for all route events.
- [ ] Missing events are visually obvious.
- [ ] Operator can add a missing pass with reason.
- [ ] Operator can reject an accepted pass.
- [ ] Operator can override a pass time.
- [ ] Operator can mark DNF/DQ/manual finished.
- [ ] Corrections are append-only and visible in correction log.
- [ ] Corrected state survives service restart.
- [ ] Corrections enqueue cloud sync payloads.
```

- [ ] **Step 2: Update docs**

Update `README.md` current status with:

```markdown
- Manual review/correction design and implementation.
```

Update `AGENTS.md` architecture notes with:

```markdown
Manual corrections are append-only facts. Do not edit or delete accepted events to correct race results; derive corrected state through review projection.
```

- [ ] **Step 3: Run full verification**

```bash
cd apps/local-core
uv run pytest -v
```

```bash
cd apps/admin
npm test -- --run
npm run build
```

```bash
cd apps/cloud-spectator
npm test -- --run
npm run typecheck
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add README.md AGENTS.md docs/acceptance/manual-review-corrections.md
git commit -m "docs: document manual review corrections"
```

