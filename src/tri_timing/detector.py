from __future__ import annotations

from tri_timing.models import DetectionPolicy, PassCandidate


class PassDetector:
    def __init__(self, policy: DetectionPolicy):
        self.policy = policy
        self._samples: list[tuple[float, int]] = []
        self._candidate_samples: list[tuple[float, int]] = []
        self._candidate_opened_at: float | None = None
        self._candidate_confirmed = False
        self._last_strong_time: float | None = None
        self._last_closed_at: float | None = None
        self.last_candidate: PassCandidate | None = None

    def observe(self, *, timestamp_sec: float, rssi: int) -> PassCandidate | None:
        self._samples.append((timestamp_sec, rssi))
        self._samples = [
            sample
            for sample in self._samples
            if timestamp_sec - sample[0] <= self.policy.window_sec
        ]

        if (
            self._last_closed_at is not None
            and timestamp_sec - self._last_closed_at < self.policy.cooldown_sec
        ):
            return None

        if (
            rssi >= self.policy.strong_rssi_threshold
            and self._candidate_opened_at is None
        ):
            self._candidate_opened_at = timestamp_sec
            self._candidate_samples = []
            self._candidate_confirmed = False

        if self._candidate_opened_at is not None:
            self._candidate_samples.append((timestamp_sec, rssi))

        if rssi >= self.policy.strong_rssi_threshold:
            self._last_strong_time = timestamp_sec

        if self._candidate_opened_at is None:
            return None

        window_strong_samples = [
            sample
            for sample in self._samples
            if sample[1] >= self.policy.strong_rssi_threshold
        ]
        if len(window_strong_samples) >= self.policy.min_packets:
            self._candidate_confirmed = True

        if not self._candidate_confirmed:
            return None

        clear_started = (
            self._last_strong_time is not None
            and timestamp_sec - self._last_strong_time >= self.policy.clear_sec
        )
        is_below_close = rssi <= self.policy.close_rssi_threshold
        if not clear_started or not is_below_close:
            return None

        peak_time, peak_rssi = max(self._candidate_samples, key=lambda sample: sample[1])
        candidate = PassCandidate(
            candidate_id=f"candidate-{int(self._candidate_opened_at)}-{int(timestamp_sec)}",
            opened_at_sec=self._candidate_opened_at,
            peak_time_sec=peak_time,
            closed_at_sec=timestamp_sec,
            strongest_rssi=peak_rssi,
            packet_count=len(self._candidate_samples),
            confidence="high"
            if peak_rssi >= self.policy.strong_rssi_threshold
            else "medium",
        )
        self.last_candidate = candidate
        self._candidate_opened_at = None
        self._candidate_samples = []
        self._candidate_confirmed = False
        self._samples = []
        self._last_strong_time = None
        self._last_closed_at = timestamp_sec
        return candidate
