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
        if (
            self._last_closed_at is not None
            and timestamp_sec - self._last_closed_at < self.policy.cooldown_sec
        ):
            self._samples = []
            self._reset_candidate()
            return None

        self._samples.append((timestamp_sec, rssi))
        self._samples = self._recent_samples(self._samples, timestamp_sec)
        self._expire_stale_candidate(timestamp_sec)

        if (
            rssi >= self.policy.strong_rssi_threshold
            and self._candidate_opened_at is None
        ):
            self._candidate_opened_at = timestamp_sec
            self._candidate_samples = []
            self._candidate_confirmed = False

        if self._candidate_opened_at is not None:
            self._candidate_samples.append((timestamp_sec, rssi))
            if not self._candidate_confirmed:
                self._candidate_samples = self._recent_samples(
                    self._candidate_samples, timestamp_sec
                )

        if rssi >= self.policy.strong_rssi_threshold:
            self._last_strong_time = timestamp_sec

        if self._candidate_opened_at is None:
            return None

        candidate_strong_samples = [
            sample
            for sample in self._candidate_samples
            if sample[1] >= self.policy.strong_rssi_threshold
        ]
        if len(candidate_strong_samples) >= self.policy.min_packets:
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
        packet_count = len(self._candidate_samples)
        candidate = PassCandidate(
            candidate_id=(
                "candidate-"
                f"{self._format_timestamp(self._candidate_opened_at)}-"
                f"{self._format_timestamp(peak_time)}-"
                f"{self._format_timestamp(timestamp_sec)}-"
                f"{peak_rssi}-{packet_count}"
            ),
            opened_at_sec=self._candidate_opened_at,
            peak_time_sec=peak_time,
            closed_at_sec=timestamp_sec,
            strongest_rssi=peak_rssi,
            packet_count=packet_count,
            confidence="high"
            if peak_rssi >= self.policy.strong_rssi_threshold
            else "medium",
        )
        self.last_candidate = candidate
        self._reset_candidate()
        self._samples = []
        self._last_closed_at = timestamp_sec
        return candidate

    def _recent_samples(
        self, samples: list[tuple[float, int]], timestamp_sec: float
    ) -> list[tuple[float, int]]:
        return [
            sample
            for sample in samples
            if timestamp_sec - sample[0] <= self.policy.window_sec
        ]

    def _expire_stale_candidate(self, timestamp_sec: float) -> None:
        if self._candidate_opened_at is None or self._candidate_confirmed:
            return

        self._candidate_samples = self._recent_samples(
            self._candidate_samples, timestamp_sec
        )
        strong_activity_stale = (
            self._last_strong_time is not None
            and timestamp_sec - self._last_strong_time > self.policy.window_sec
        )
        if not self._candidate_samples or strong_activity_stale:
            self._reset_candidate()

    def _reset_candidate(self) -> None:
        self._candidate_opened_at = None
        self._candidate_samples = []
        self._candidate_confirmed = False
        self._last_strong_time = None

    def _format_timestamp(self, timestamp_sec: float) -> str:
        return f"{round(timestamp_sec * 1000):013d}"
