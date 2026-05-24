# BLE Triathlon Timing MVP Design

Date: 2026-05-25
Status: Draft for user review

## Summary

Build a friendly-race BLE timing system for triathlon/duathlon-style events.

The MVP is a working local timing setup with real hardware and software:

- Athlete wears a configurable iBeacon wristband/tag.
- One laptop with one USB BLE dongle acts as the local timing authority.
- A Python local service scans BLE, stores observations, detects checkpoint passes, advances race state, and exposes a local API.
- A local React admin UI supports race-day operation and manual adjudication.
- Cloudflare is used only for spectator views and backup sync, not official timing.

This is BLE-assisted local timing with manual adjudication. It is not certified chip timing.

## Core Decisions

- Use configurable iBeacon wristband tags for MVP.
- Prefer low-cost `nRF52810` tags if they support continuous configurable iBeacon advertising.
- Use one laptop, one USB BLE dongle, and one shared timing gate for MVP.
- Keep the local laptop as the only official race authority.
- Keep cloud sync one-way: local to cloud.
- Use file-based race setup instead of a heavy setup UI.
- Use an ordered route with laps, not a general graph state machine.
- Store authoritative data in local SQLite with append-only facts.
- Treat JSONL/R2 as derived backup/export, not equal source of truth.
- Keep failure handling pragmatic because this is a friendly competition.

## Hardware Assumptions

Athlete side:

- Configurable iBeacon wristband/tag.
- Beacon identity from `UUID + Major + Minor`.
- Backend maps beacon identity to athlete.
- Desired advertising interval: 100-250 ms if supported.
- Desired TX power: configurable and tuned during field tests.

Checkpoint side:

- Laptop.
- One USB BLE dongle.
- USB extension cable.
- Phone hotspot for cloud sync.
- Local power source.

Vendor questions before buying many tags:

- Is the price for one tag or multiple?
- Can color be selected?
- Is continuous standard iBeacon advertising supported?
- Can `UUID`, `Major`, and `Minor` be configured by app?
- What is the minimum advertising interval?
- Is 100 ms or 200 ms supported?
- What is maximum TX power?
- What battery is used, and is it replaceable?
- Does configuration persist after power/battery change?
- Is Android APK available, and what is the iOS app name?
- Is SDK/SWD/custom firmware supported? Not required for MVP, but useful to know.

## Runtime Architecture

```text
BLE iBeacon wristband
  -> USB BLE dongle
  -> Python local race service
  -> local SQLite canonical store
  -> local React admin UI
  -> queued Cloudflare sync
  -> cloud spectator dashboard
  -> optional R2 backup/export
```

The Python local service owns:

- BLE scanning.
- Raw detection ingest.
- Pass detection.
- Ordered route state.
- Manual correction validation.
- REST/SSE API for admin UI.
- Sync queue.
- Local exports.

The React admin UI owns:

- Display.
- Operator commands.
- Manual correction forms.

It must not own timing logic, route advancement logic, or ordering rules.

Cloudflare owns:

- Public spectator read model.
- Latest leaderboard/status snapshots.
- Confirmed event/correction display.
- Optional raw/export backup via R2.

Cloudflare does not feed back into local official state for MVP.

## Local Authority And Audit Model

BLE detections are evidence, not timing facts.

Processing pipeline:

```text
raw_packet
  -> presence_window
  -> pass_candidate
  -> route_decision
  -> accepted_route_event | stored_warning | ignored_duplicate
```

Authoritative facts are append-only:

- Raw detections.
- Pass candidates.
- Accepted route events.
- Manual corrections.
- Config snapshots.
- Sync outbox items.

Current athlete states and leaderboards are projections. They must be rebuildable from config snapshots plus append-only facts and corrections.

Manual corrections are compensating events, never in-place edits. Example correction types:

- `insert_pass`
- `invalidate_pass`
- `override_time`
- `mark_dns`
- `mark_dnf`
- `mark_dq`
- `reassign_beacon`

Every correction records operator, reason, target event/candidate, old value, new value, created time, and effective race time where applicable.

## Route Model

Race setup is defined in config files:

- `race.yaml`
- `athletes.csv` or `athletes.yaml`
- `receivers.yaml`

Human route config is compiled into a versioned ordered list of route events. The compiled route version freezes at race start.

The state machine advances by `next_route_event_index` per athlete. It does not store independent lap counters or hidden transition state if those can be derived from the route event index.

Example compiled duathlon route:

```text
run1_lap1_complete
run1_lap2_complete
run1_lap3_complete
run1_complete_t1_in
t1_out_bike_start
bike_lap1_complete
bike_lap2_complete
bike_complete_t2_in
t2_out_run2_start
run2_lap1_complete
run2_lap2_complete
run2_lap3_complete
finish
```

Starts are derived:

- `run1` starts at race start.
- `lap2` starts when `lap1_complete` is accepted.
- `t1` starts at `run1_complete_t1_in`.
- `bike` starts at `t1_out_bike_start`.
- `run2` starts at `t2_out_run2_start`.

Each route event includes:

- `id`
- `index`
- `label`
- `checkpoint_id`
- `kind`
- `sport`
- `min_elapsed_sec`
- `cooldown_sec`
- `detection_policy_id`
- `manual_allowed`

`detection_policy_id` allows different RSSI/window rules for different route states. For example:

- Open run/bike lap checkpoints can use a normal policy with moderate RSSI thresholds.
- Shared-gate transition entry/exit can use a stricter policy with higher strong-RSSI threshold, longer clear requirement, and `min_transition_sec`.
- Finish can use stricter confidence rules and stronger manual-review prompts for close or ambiguous finishes.

The same physical checkpoint can satisfy different semantic events. Route expectation disambiguates meaning.

## Race Phases

```text
pre_start: scan/store raw only
armed: ready for start, no route advancement
live: normal route advancement
closed: official route advancement stopped, corrections allowed
```

Mass start flow:

1. Scanner stays on before race.
2. Admin checks all expected beacons.
3. Admin clicks Start.
4. `race_start_at` is recorded.
5. `start_grace_until` suppresses route advancement for configured seconds.
6. First expected event is `run1_lap1_complete`.
7. First lap also requires `min_elapsed_sec`.

Do not turn off scanning at start. Store raw detections throughout.

## Pass Detection

Use hysteresis, not one RSSI threshold.

Candidate behavior:

- Open candidate when RSSI/window/packet rules pass.
- Track strongest RSSI sample.
- Estimate pass time using `peak_time`, not close time.
- Close candidate after RSSI stays below close threshold or beacon is absent for `clear_seconds`.
- Store suppressed candidates with reason.

Policies are configurable per checkpoint and per route event. This is important because the same receiver may need different behavior depending on athlete state:

- Lap completion: tolerate moderate signal if `min_elapsed_sec` makes false repeats unlikely.
- Transition entry: require a strong gate-crossing peak.
- Transition exit: require strong peak, prior clear condition, cooldown, and transition minimum time.
- Finish: require strong confidence or surface review warning.

Separate:

- Short detection cooldown/debounce, usually seconds.
- Route `min_elapsed_sec`, usually minutes depending lap distance.

Candidate metadata:

- `candidate_opened_at`
- `peak_at`
- `closed_at`
- `derived_at`
- `strongest_rssi`
- `median_rssi`
- `packet_count`
- `raw_detection_sequence_range`
- `confidence`
- `suppression_reason` if not accepted

Only the expected next route event can advance. Strong out-of-order detections are stored and warned, but do not auto-advance state.

## Transitions

Represent transitions as explicit route boundary events:

- `run1_complete_t1_in`
- `t1_out_bike_start`
- `bike_complete_t2_in`
- `t2_out_run2_start`

Same shared gate can detect transition in/out if there is a distinct later RSSI peak.

For transition out:

- Prior transition in must be accepted.
- `min_transition_sec` must pass.
- Transition-specific detection policy must pass, usually stricter than normal lap policy.
- A real clear condition must happen before a new candidate opens.
- Cooldown must pass.
- Manual fallback must be available.

If transition area is too close and RSSI contrast is poor, automatic transition precision is not guaranteed. Use manual adjudication if needed.

## Data Model

SQLite is canonical.

Use durable local sequence numbers as the ordering spine. Wall clock is for display/export, not authoritative ordering.

Canonical tables:

- `raw_detections`
- `pass_candidates`
- `accepted_route_events`
- `manual_corrections`
- `config_snapshots`
- `sync_outbox`
- `sync_attempts`
- `raw_bundle_manifest`

Derived tables:

- `current_athlete_states`
- `leaderboard_snapshot`
- `receiver_health_current`

Operational history:

- `receiver_health_events`
- `scan_rate_samples`
- `process_lifecycle_events`

Important fields:

- `local_sequence_number`
- `race_id`
- `athlete_id`
- `bib`
- `beacon_id`
- `receiver_id`
- `checkpoint_id`
- `source_node_id`
- `process_instance_id`
- `boot_id`
- `timestamp_monotonic`
- `timestamp_wall`
- `algorithm_version`
- `parameter_hash`
- `config_snapshot_id`
- `idempotency_key`
- `payload_hash`

Crash consistency rule:

Commit canonical event, projection update, and sync outbox row in one SQLite transaction. Export JSONL/R2 asynchronously from committed SQLite sequence ranges.

## Cloud Sync

Cloud sync is one-way and idempotent.

Local to cloud payloads:

- Confirmed route events.
- Manual corrections.
- Leaderboard/status snapshots.
- Receiver/sync freshness.
- Optional raw bundle manifests.

Outbox requirements:

- Stable idempotency key per item.
- Payload hash.
- Status: `pending`, `sending`, `acked`, `failed_retryable`, `failed_permanent`.
- Retry count.
- Next retry time.
- Last error.
- Remote ack ID.

Cloud ingest rule:

- Same idempotency key and same payload hash is safe duplicate.
- Same idempotency key and different payload hash is integrity error.

Cloudflare usage:

- D1 for spectator read model/projection.
- R2 for raw bundles, SQLite exports, and snapshot archives.
- KV only for cache/public latest views, not correctness.
- Durable Objects optional later for serialized ingest or live fanout.

Public dashboard exposes only bib/display name/category/result state. Raw BLE IDs, diagnostics, operator notes, and private payloads remain private.

## Local Admin UI

The admin UI is an operator console, not a full race builder.

Screens:

- Setup/check-in.
- Calibration.
- Race control.
- Receiver health.
- Live timing.
- Warnings/review.
- Manual correction.
- Export.

Critical indicators:

- Scanner healthy.
- DB writing.
- Last raw packet.
- Scan rate.
- Disk space.
- Sync age.
- Backup/export age.
- All expected beacons seen.
- Duplicate/missing/unknown beacons.
- Weak beacons.
- Calibration pass/fail.

Manual tools:

- Manual timestamp button.
- Add pass.
- Invalidate pass.
- Override time.
- Mark DNS/DNF/DQ.
- Reassign beacon.
- Lock/finalize results.

## Spectator Dashboard

Keep spectator UI simple:

- Leaderboard.
- Athlete current segment/lap.
- Last checkpoint time.
- Finish status.
- Last updated/sync freshness.
- Provisional/corrected indicator when relevant.

If cloud sync is stale, the dashboard must show freshness clearly.

## Calibration

Calibration uses the actual race setup:

- Actual laptop.
- Actual dongle.
- Actual wristbands.
- Actual athlete placement.
- Actual gate and transition layout.

Measure:

- Gate RSSI peak.
- Transition/rack RSSI background.
- Missed reads.
- Duplicate reads.
- First-seen latency.
- Strongest-RSSI timing.
- Group pass behavior.
- Wrist/body orientation.

Target:

- Gate vs transition RSSI contrast should be useful, ideally 10 dB or more.
- If contrast is poor, use manual-assisted mode for affected events.

## Friendly-Race Fallbacks

Because this is a friendly competition, heavy failure hardening is not part of the first MVP.

Keep lightweight fallbacks:

- Manual correction UI.
- Local CSV/JSON export.
- Optional paper bib sheet.
- Optional phone video pointed at gate for close/disputed finishes.
- Manual comparison after race if system fails.

Cloud can be offline for the whole race. Local export remains official.

## MVP Scope

In scope:

- Python local race service.
- SQLite canonical store.
- BLE scanner for iBeacon UUID/Major/Minor.
- RSSI/window pass detector.
- Ordered route/lap state machine.
- Manual correction commands.
- Local REST/SSE API.
- Local React admin UI.
- Cloudflare spectator snapshot/event sync.
- Basic R2/export backup.
- Post-race replay/export CLI.

Phase 1.5:

- Rich replay UI.
- Advanced R2 backup workflows.
- Historical race browser.
- Polished admin filtering/bulk edits.
- Full route setup builder.
- Multi-checkpoint merge.
- More formal race-day failure drills.

Non-goals:

- Phone-as-beacon timing.
- Certified chip timing.
- Cloud-authoritative admin.
- Distributed multi-checkpoint merge.
- Graph/branching route model.
- Fancy map/ETA/visualization features.
- Automatic transition precision when RSSI contrast is poor.

## Test Priorities

Core tests:

- Mass start packets do not create lap events.
- Lingering creates one pass only.
- Same checkpoint maps to different semantic events by route expectation.
- Too-early lap is stored but does not advance route.
- Out-of-order pass is warned but not advanced.
- Manual correction rebuilds projection deterministically.
- Restart/replay reproduces same leaderboard.

Hardware tests:

- 10+ pass-throughs per tag position.
- Walking and running speed.
- Group pass.
- Wrist orientation/body shielding.
- Shared gate transition in/out.
- Scanner restart.

Operator tests:

- Start race.
- Add pass.
- Invalidate pass.
- Override time.
- Reassign beacon.
- Export official results.
- Cloud offline during race.

## Deferred Implementation Choices

These are intentionally deferred to implementation planning. They do not change the MVP architecture.

- Exact iBeacon tag model and confirmed configuration limits.
- BLE dongle model and OS support.
- Python BLE library details.
- Exact route config YAML schema.
- Exact Cloudflare products for spectator sync implementation.
- Whether local React app is served by Python or run as separate dev/static app.
