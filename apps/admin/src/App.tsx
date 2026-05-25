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

  useEffect(() => {
    const events = new EventSource("/api/events/stream");
    events.addEventListener("state", (event) => {
      setState(JSON.parse(event.data) as RaceStateView);
    });
    events.onerror = () => {
      setError("Live event stream disconnected");
    };
    return () => events.close();
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
        <p>
          Phase: <strong>{state?.phase ?? "connecting"}</strong>
        </p>
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
    </main>
  );
}
