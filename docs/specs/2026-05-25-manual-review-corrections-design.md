# Manual Review And Corrections Design

Date: 2026-05-25
Status: Draft for implementation planning

## Summary

Add a minimal race-day review and correction layer for the local timing authority. The goal is not a full admin system. The goal is fast, safe adjudication when BLE misses, duplicates, weak RSSI, or operator judgment require a manual fix.

The local Python service remains authoritative. Corrections are append-only facts in SQLite. The React admin UI displays a review-focused operator screen and sends explicit correction commands. Cloud spectator sync receives the corrected local truth through the existing sync outbox.

## Goals

- Let an operator correct timing during a live race or after close.
- Keep all correction actions auditable and replayable.
- Avoid destructive edits to accepted events or raw detections.
- Make the UI usable by a non-racing helper under time pressure.
- Show missing, rejected, manual, and overridden route events clearly.
- Keep implementation small enough for MVP.

## Non-Goals

- Full route editor.
- Bulk correction tools.
- Multi-user roles or authentication.
- Rich raw BLE replay UI.
- Certified timing workflow.
- Cloud-side correction authority.

## Correction Model

Add an append-only `manual_corrections` table:

```text
manual_corrections
- local_sequence_number INTEGER PRIMARY KEY
- race_id TEXT NOT NULL
- correction_type TEXT NOT NULL
- athlete_id TEXT NOT NULL
- route_event_id TEXT
- target_local_sequence_number INTEGER
- corrected_time_wall TEXT
- status TEXT
- reason TEXT NOT NULL
- created_at TEXT NOT NULL
- created_by TEXT NOT NULL
```

Initial correction types:

- `manual_add_pass`: add a missing route event for an athlete at a wall-clock timestamp.
- `manual_reject_pass`: reject an existing accepted event by `target_local_sequence_number`.
- `manual_override_time`: override an existing accepted/manual event timestamp.
- `mark_status`: set athlete status such as `dnf`, `dq`, `manual_finished`, or `racing`.

Every correction gets its own local sequence number and sync outbox item. The original accepted event remains stored.

## Projection Rules

Runtime review state is derived in this order:

1. Race config and route events.
2. Accepted route events from the timing engine.
3. Manual corrections ordered by `local_sequence_number`.

Projection behavior:

- `manual_add_pass` creates a manual event if the athlete and route event exist.
- `manual_reject_pass` marks the target event as rejected.
- `manual_override_time` changes the displayed/event time but preserves original time in details.
- `mark_status` changes athlete status.
- Invalid stale corrections remain visible as warnings instead of crashing projection.

The race engine does not silently mutate history. Corrections affect the review/export projection and corrected race state.

## Local API

Add endpoints:

```text
GET  /api/review/state
GET  /api/corrections
POST /api/corrections
```

`GET /api/review/state` returns:

- race phase
- route events
- athlete review cards
- corrected event timeline per athlete
- missing expected events
- rejected/overridden/manual flags
- recent raw detections
- correction log

`POST /api/corrections` accepts one command:

```json
{
  "correction_type": "manual_add_pass",
  "athlete_id": "A001",
  "route_event_id": "run1_lap2_complete",
  "corrected_time_wall": "2026-05-25T09:21:00+08:00",
  "reason": "Saw athlete cross while BLE missed",
  "created_by": "operator"
}
```

Validation rules:

- Unknown athlete returns `400`.
- Unknown route event returns `400`.
- Missing reason returns `400`.
- Reject/override must reference an existing event sequence.
- Corrections are allowed in `live` and `closed` phases.

## Admin UI

Add a `Review` mode to `apps/admin`, not a separate app.

Layout:

```text
Top bar: phase, cloud sync age, local service status
Left: athlete cards sorted by attention needed
Center: selected athlete route timeline
Right: correction form + raw detections near selected event
Bottom: recent correction log
```

Athlete cards show:

- name and bib
- current status
- next expected event
- completed / total event count
- warning badges: `missing`, `manual`, `rejected`, `overridden`

Timeline rows show:

- route event label
- status: `pending`, `accepted`, `missing`, `manual`, `overridden`, `rejected`
- timestamp
- confidence
- source: `ble`, `manual`, `override`

Fast actions:

- Add missing pass.
- Reject selected pass.
- Override selected time.
- Mark DNF/DQ/manual finished.

Each action opens a confirmation modal with plain language:

```text
Add manual pass for Bob at Run 1 Lap 2, time 09:21:00?
Reason: Saw athlete cross while BLE missed.
```

## UX Principles

- Optimize for a tired helper with one laptop.
- Use large click targets and clear color states.
- Default view should answer: “who needs attention now?”
- Manual changes must be obvious, not hidden.
- Avoid tables as the primary UI. Use cards and timelines.
- Never make operator type route event IDs manually.
- Keep correction forms short: action, athlete, event, time, reason.

## Cloud Sync

Corrections enqueue sync payloads through the existing local outbox.

Initial cloud behavior:

- Include correction effects in `race_state_snapshot`.
- Enqueue a `manual_correction` sync payload for audit visibility.
- Cloud remains read-only and never accepts correction commands.

## Testing

Python tests:

- Store appends correction facts.
- Review projection applies add/reject/override/status in sequence.
- Invalid corrections produce warnings, not crashes.
- API validates correction commands.
- Corrections enqueue sync items.

Admin tests:

- Review screen renders attention-sorted athlete cards.
- Timeline shows accepted, missing, manual, overridden, rejected states.
- Correction form posts expected payload.
- Confirmation modal prevents accidental one-click edits.

Manual no-hardware check:

1. Start race with fixture config.
2. Use synthetic detections to accept one event.
3. Add missing pass for another event.
4. Reject the synthetic pass.
5. Override a timestamp.
6. Mark an athlete DNF.
7. Confirm review state and cloud snapshot reflect corrected truth.
