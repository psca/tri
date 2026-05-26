import { useEffect, useState } from "react";
import {
  closeRace,
  getRaceState,
  getReceiverHealth,
  getReviewState,
  sendSyntheticDetection,
  startRace,
  submitCorrection,
} from "./api";
import type {
  ManualCorrectionRequest,
  RaceStateView,
  ReceiverHealthResponse,
  ReviewAthlete,
  ReviewState,
  ReviewTimelineEvent,
} from "./types";
import "./styles.css";

type Mode = "live" | "review";
type CorrectionType = ManualCorrectionRequest["correction_type"];
type PendingCorrection = {
  payload: ManualCorrectionRequest;
  summary: string[];
};

const correctionLabels: Record<CorrectionType, string> = {
  manual_add_pass: "Add missing pass",
  manual_reject_pass: "Reject pass",
  manual_override_time: "Override time",
  mark_status: "Mark status",
};

export function App() {
  const [state, setState] = useState<RaceStateView | null>(null);
  const [receiverHealth, setReceiverHealth] = useState<ReceiverHealthResponse | null>(null);
  const [reviewState, setReviewState] = useState<ReviewState | null>(null);
  const [mode, setMode] = useState<Mode>("live");
  const [selectedAthleteId, setSelectedAthleteId] = useState<string | null>(null);
  const [selectedRouteEventId, setSelectedRouteEventId] = useState<string | null>(null);
  const [correctionType, setCorrectionType] = useState<CorrectionType>("manual_add_pass");
  const [correctedTime, setCorrectedTime] = useState("");
  const [status, setStatus] = useState("dnf");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pendingCorrection, setPendingCorrection] = useState<PendingCorrection | null>(null);

  useEffect(() => {
    getRaceState().then(setState).catch((err: Error) => setError(err.message));
    getReceiverHealth().then(setReceiverHealth).catch((err: Error) => setError(err.message));
    refreshReview();
  }, []);

  useEffect(() => {
    const events = new EventSource("/api/events/stream");
    events.addEventListener("state", (event) => {
      setState(JSON.parse(event.data) as RaceStateView);
    });
    events.addEventListener("review_state", (event) => {
      applyReviewState(JSON.parse(event.data) as ReviewState);
    });
    events.onerror = () => {
      setError("Live event stream disconnected");
    };
    return () => events.close();
  }, []);

  useEffect(() => {
    if (mode === "review") {
      refreshReview();
    }
  }, [mode]);

  function applyReviewState(nextState: ReviewState) {
    setReviewState(nextState);
    setSelectedAthleteId((current) => current ?? nextState.athletes?.[0]?.athlete_id ?? null);
    setSelectedRouteEventId((current) => current ?? nextState.route_events?.[0]?.id ?? null);
  }

  async function refreshReview() {
    try {
      applyReviewState(await getReviewState());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  async function run(action: () => Promise<RaceStateView>) {
    setError(null);

    try {
      setState(await action());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  function stageCorrection() {
    setError(null);
    setPendingCorrection(null);

    if (!selectedAthleteId) {
      setError("Select an athlete before correcting.");
      return;
    }
    if (correctionType !== "mark_status" && !selectedRouteEventId) {
      setError("Select a route event before correcting.");
      return;
    }
    if (!reason.trim()) {
      setError("Reason is required for manual corrections.");
      return;
    }
    if (
      (correctionType === "manual_add_pass" || correctionType === "manual_override_time") &&
      !correctedTime.trim()
    ) {
      setError("Corrected time is required for this correction.");
      return;
    }

    const selectedEvent = selectedTimelineEvent(reviewState, selectedAthleteId, selectedRouteEventId);
    const payload: ManualCorrectionRequest = {
      correction_type: correctionType,
      athlete_id: selectedAthleteId,
      route_event_id: correctionType === "mark_status" ? null : selectedRouteEventId,
      reason: reason.trim(),
      created_by: "operator",
    };

    if (correctionType === "manual_add_pass" || correctionType === "manual_override_time") {
      payload.corrected_time_wall = correctedTime.trim();
    }
    if (correctionType === "manual_reject_pass" || correctionType === "manual_override_time") {
      payload.target_local_sequence_number = correctionTargetSequence(selectedEvent);
      if (payload.target_local_sequence_number == null) {
        setError("Selected event has no accepted or correction sequence to target.");
        return;
      }
    }
    if (correctionType === "mark_status") {
      payload.status = status === "finished" ? "manual_finished" : status;
    }

    setPendingCorrection({
      payload,
      summary: [
        `Action: ${correctionLabels[correctionType]}`,
        `Athlete: ${selectedAthlete?.name ?? selectedAthleteId}`,
        `Route event: ${correctionType === "mark_status" ? "none" : selectedEvent?.label ?? selectedRouteEventId}`,
        ...(payload.target_local_sequence_number != null ? [`Target sequence: ${payload.target_local_sequence_number}`] : []),
        ...(payload.corrected_time_wall ? [`Corrected time: ${payload.corrected_time_wall}`] : []),
        ...(payload.status ? [`Status: ${payload.status}`] : []),
        `Reason: ${payload.reason}`,
      ],
    });
  }

  async function confirmCorrection() {
    if (!pendingCorrection) {
      return;
    }

    try {
      applyReviewState(await submitCorrection(pendingCorrection.payload));
      setPendingCorrection(null);
      setReason("");
      await refreshReview();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  const selectedAthlete =
    reviewState?.athletes.find((athlete) => athlete.athlete_id === selectedAthleteId) ??
    reviewState?.athletes[0] ??
    null;
  const selectedEvent =
    selectedAthlete?.timeline.find((event) => event.route_event_id === selectedRouteEventId) ??
    selectedAthlete?.timeline[0] ??
    null;
  const needsTarget = correctionType === "manual_reject_pass" || correctionType === "manual_override_time";
  const targetSequence = correctionTargetSequence(selectedEvent);
  const submitDisabled = needsTarget && targetSequence == null;

  return (
    <main className="shell">
      <section className="hero">
        <p className="eyebrow">Local Race Authority</p>
        <h1>Tri Timing Admin</h1>
        <p>
          Phase: <strong>{state?.phase ?? "connecting"}</strong>
        </p>
        {error ? <p role="alert">{error}</p> : null}
        <div className="mode-tabs" role="tablist" aria-label="Admin mode">
          <button
            aria-selected={mode === "live"}
            role="tab"
            className={mode === "live" ? "active" : ""}
            onClick={() => setMode("live")}
          >
            Live
          </button>
          <button
            aria-selected={mode === "review"}
            role="tab"
            className={mode === "review" ? "active" : ""}
            onClick={() => setMode("review")}
          >
            Review
          </button>
        </div>
        <div className="controls">
          <button onClick={() => run(startRace)}>Start Race</button>
          <button onClick={() => run(closeRace)}>Close Race</button>
        </div>
      </section>

      {mode === "live" ? (
        <>
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

          <section className="panel receiver-health">
            <h2>Receiver Health</h2>
            {receiverHealth?.receivers?.length ? (
              receiverHealth.receivers.map((receiver) => (
                <article className={`receiver-card ${receiver.status}`} key={receiver.receiver_id}>
                  <div>
                    <strong>{receiver.receiver_id}</strong>
                    <span>{receiver.checkpoint_id}</span>
                  </div>
                  <strong>{receiver.status}</strong>
                  <p>
                    Known {receiver.known_packets} · Unknown {receiver.unknown_packets}
                  </p>
                  <p>Last packet {receiver.last_packet_wall ?? "never"}</p>
                  {receiver.latest_known_beacons.map((beacon) => (
                    <p key={`${receiver.receiver_id}-${beacon.athlete_id}`}>
                      {beacon.athlete_id} · {beacon.rssi} dBm
                    </p>
                  ))}
                </article>
              ))
            ) : (
              <p>No receivers reported yet.</p>
            )}
          </section>

          <section className="panel">
            <h2>Recent Detections</h2>
            {state?.raw_detections.length ? (
              state.raw_detections.map((detection) => (
                <p key={detection.local_sequence_number}>
                  {detection.receiver_id} · {detection.checkpoint_id} · {detection.rssi} dBm
                </p>
              ))
            ) : (
              <p>No raw detections yet.</p>
            )}
          </section>
        </>
      ) : (
        <section className="review-grid">
          <section className="panel">
            <h2>Review Queue</h2>
            {reviewState?.athletes.length ? (
              reviewState.athletes.map((athlete) => (
                <AthleteReviewButton
                  athlete={athlete}
                  isSelected={athlete.athlete_id === selectedAthlete?.athlete_id}
                  key={athlete.athlete_id}
                  onSelect={() => {
                    setSelectedAthleteId(athlete.athlete_id);
                    setSelectedRouteEventId(athlete.timeline[0]?.route_event_id ?? null);
                  }}
                />
              ))
            ) : (
              <p>No athletes in review state.</p>
            )}
          </section>

          <section className="panel timeline-panel">
            <h2>{selectedAthlete ? `${selectedAthlete.name} Timeline` : "Timeline"}</h2>
            {selectedAthlete?.timeline.map((event) => (
              <button
                className={event.route_event_id === selectedEvent?.route_event_id ? "timeline-event active" : "timeline-event"}
                key={event.route_event_id}
                onClick={() => setSelectedRouteEventId(event.route_event_id)}
              >
                <strong>{event.label}</strong>
                <span>{event.status}</span>
                <span>{event.timestamp ?? "No time"}</span>
                <span>confidence: {event.confidence ?? "none"}</span>
                <span>source: {event.source}</span>
              </button>
            ))}
          </section>

          <section className="panel correction-panel">
            <h2>Correction</h2>
            <p>
              {selectedAthlete?.name ?? "No athlete"} · {selectedEvent?.label ?? "No route event"}
            </p>
            {needsTarget ? (
              <p className={targetSequence == null ? "hint warn" : "hint"}>
                {targetSequence == null
                  ? "No accepted or correction sequence is available for this action."
                  : `Targets sequence #${targetSequence}`}
              </p>
            ) : null}
            <fieldset>
              <legend>Action</legend>
              {(Object.keys(correctionLabels) as CorrectionType[]).map((type) => (
                <label key={type}>
                  <input
                    checked={correctionType === type}
                    name="correction_type"
                    onChange={() => setCorrectionType(type)}
                    type="radio"
                  />
                  {correctionLabels[type]}
                </label>
              ))}
            </fieldset>
            {(correctionType === "manual_add_pass" || correctionType === "manual_override_time") && (
              <label>
                Corrected time
                <input
                  onChange={(event) => setCorrectedTime(event.target.value)}
                  placeholder="2026-05-25T09:10:00+08:00"
                  value={correctedTime}
                />
              </label>
            )}
            {correctionType === "mark_status" && (
              <label>
                Status
                <select onChange={(event) => setStatus(event.target.value)} value={status}>
                  <option value="dnf">DNF</option>
                  <option value="dq">DQ</option>
                  <option value="racing">Racing</option>
                  <option value="finished">Finished</option>
                </select>
              </label>
            )}
            <label>
              Reason
              <textarea
                onChange={(event) => setReason(event.target.value)}
                required
                rows={4}
                value={reason}
              />
            </label>
            <button disabled={submitDisabled} onClick={stageCorrection}>Submit correction</button>
            {pendingCorrection ? (
              <section aria-label="Confirm correction" className="confirm-panel">
                <h3>Confirm correction</h3>
                <p>Review this plain action summary before submitting.</p>
                <ul>
                  {pendingCorrection.summary.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
                <div className="confirm-actions">
                  <button onClick={confirmCorrection}>Confirm submit</button>
                  <button className="secondary" onClick={() => setPendingCorrection(null)}>
                    Cancel
                  </button>
                </div>
              </section>
            ) : null}
          </section>

          <section className="panel evidence-panel">
            <h2>Recent Raw Detections</h2>
            {reviewState?.raw_detections.length ? (
              reviewState.raw_detections.map((detection) => (
                <p key={detection.local_sequence_number}>
                  #{detection.local_sequence_number} · {detection.receiver_id} · {detection.checkpoint_id} ·{" "}
                  {detection.rssi} dBm · {detection.timestamp_wall}
                </p>
              ))
            ) : (
              <p>No raw detections in review state.</p>
            )}
          </section>

          <section className="panel evidence-panel">
            <h2>Correction Log</h2>
            {reviewState?.correction_log.length ? (
              reviewState.correction_log.map((entry, index) => (
                <pre key={index}>{JSON.stringify(entry, null, 2)}</pre>
              ))
            ) : (
              <p>No manual corrections logged.</p>
            )}
          </section>
        </section>
      )}
    </main>
  );
}

function selectedTimelineEvent(
  reviewState: ReviewState | null,
  athleteId: string | null,
  routeEventId: string | null,
): ReviewTimelineEvent | null {
  return (
    reviewState?.athletes
      .find((athlete) => athlete.athlete_id === athleteId)
      ?.timeline.find((event) => event.route_event_id === routeEventId) ?? null
  );
}

function correctionTargetSequence(event: ReviewTimelineEvent | null): number | null {
  return event?.accepted_local_sequence_number ?? event?.correction_sequence_numbers?.[0] ?? null;
}

function AthleteReviewButton({
  athlete,
  isSelected,
  onSelect,
}: {
  athlete: ReviewAthlete;
  isSelected: boolean;
  onSelect: () => void;
}) {
  return (
    <button className={isSelected ? "review-athlete active" : "review-athlete"} onClick={onSelect}>
      <span>
        <strong>
          {athlete.bib_number ? `#${athlete.bib_number} ` : ""}
          {athlete.name}
        </strong>
        <small>
          {athlete.completed_count}/{athlete.total_count} · {athlete.status}
        </small>
      </span>
      <span className={athlete.attention_level === "needs_attention" ? "badge warn" : "badge"}>
        {athlete.badges[0] ?? athlete.attention_level}
      </span>
    </button>
  );
}
