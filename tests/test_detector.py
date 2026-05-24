from tri_timing.detector import PassDetector
from tri_timing.models import DetectionPolicy


def policy() -> DetectionPolicy:
    return DetectionPolicy(
        id="transition_strict",
        strong_rssi_threshold=-62,
        close_rssi_threshold=-78,
        min_packets=3,
        window_sec=4,
        clear_sec=3,
        cooldown_sec=30,
    )


def test_detector_uses_peak_time_and_closes_after_clear():
    detector = PassDetector(policy())

    assert detector.observe(timestamp_sec=10, rssi=-75) is None
    assert detector.observe(timestamp_sec=11, rssi=-61) is None
    assert detector.observe(timestamp_sec=12, rssi=-58) is None
    assert detector.observe(timestamp_sec=13, rssi=-60) is None
    assert detector.observe(timestamp_sec=14, rssi=-80) is None
    assert detector.observe(timestamp_sec=17, rssi=-81) is not None

    candidate = detector.last_candidate
    assert candidate is not None
    assert candidate.peak_time_sec == 12
    assert candidate.strongest_rssi == -58
    assert candidate.packet_count == 5


def test_detector_requires_clear_before_new_candidate():
    detector = PassDetector(policy())
    for timestamp, rssi in [(10, -60), (11, -59), (12, -58), (16, -80)]:
        detector.observe(timestamp_sec=timestamp, rssi=rssi)

    assert detector.last_candidate is not None
    assert detector.observe(timestamp_sec=20, rssi=-60) is None
