from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import yaml

from tri_timing.models import (
    AthleteConfig,
    CheckpointConfig,
    DetectionPolicyConfig,
    RaceConfig,
    RaceStartConfig,
    ReceiverConfig,
    SportRouteSegmentConfig,
    StartMode,
    TransitionRouteSegmentConfig,
)


def load_race_config(path: Path) -> RaceConfig:
    with path.open("r", encoding="utf-8") as file:
        raw = yaml.safe_load(file)

    if not isinstance(raw, dict):
        raise ValueError(f"Race config must be a mapping: {path}")

    return RaceConfig(
        race_id=_required_str(raw, "race_id"),
        name=_required_str(raw, "name"),
        start=_parse_start(_required_mapping(raw, "start")),
        checkpoints=[
            CheckpointConfig(id=_required_str(item, "id"), name=_required_str(item, "name"))
            for item in _required_list(raw, "checkpoints")
        ],
        receivers=[
            ReceiverConfig(
                id=_required_str(item, "id"),
                checkpoint_id=_required_str(item, "checkpoint_id"),
            )
            for item in _required_list(raw, "receivers")
        ],
        route=[_parse_route_segment(item) for item in _required_list(raw, "route")],
        detection_policies={
            policy_id: _parse_detection_policy(policy)
            for policy_id, policy in _required_mapping(raw, "detection_policies").items()
        },
    )


def load_athletes(path: Path) -> list[AthleteConfig]:
    with path.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        return [
            AthleteConfig(
                athlete_id=_required_str(row, "athlete_id"),
                bib=_required_int(row, "bib"),
                name=_required_str(row, "name"),
                beacon_uuid=_required_str(row, "beacon_uuid"),
                beacon_major=_required_int(row, "beacon_major"),
                beacon_minor=_required_int(row, "beacon_minor"),
            )
            for row in reader
        ]


def _parse_start(raw: dict[str, Any]) -> RaceStartConfig:
    return RaceStartConfig(
        mode=StartMode(_required_str(raw, "mode")),
        checkpoint_id=_required_str(raw, "checkpoint_id"),
        start_grace_sec=_required_int(raw, "start_grace_sec"),
    )


def _parse_route_segment(raw: Any) -> SportRouteSegmentConfig | TransitionRouteSegmentConfig:
    if not isinstance(raw, dict):
        raise ValueError("Route segment must be a mapping")

    if raw.get("kind") == "transition":
        return TransitionRouteSegmentConfig(
            id=_required_str(raw, "id"),
            in_event_id=_required_str(raw, "in_event_id"),
            out_event_id=_required_str(raw, "out_event_id"),
            checkpoint_id=_required_str(raw, "checkpoint_id"),
            min_transition_sec=_required_int(raw, "min_transition_sec"),
            detection_policy_id=_required_str(raw, "detection_policy_id"),
        )

    return SportRouteSegmentConfig(
        id=_required_str(raw, "id"),
        sport=_required_str(raw, "sport"),
        checkpoint_id=_required_str(raw, "checkpoint_id"),
        laps=_required_int(raw, "laps"),
        min_lap_elapsed_sec=_required_int(raw, "min_lap_elapsed_sec"),
        detection_policy_id=_required_str(raw, "detection_policy_id"),
    )


def _parse_detection_policy(raw: Any) -> DetectionPolicyConfig:
    if not isinstance(raw, dict):
        raise ValueError("Detection policy must be a mapping")

    return DetectionPolicyConfig(
        strong_rssi_threshold=_required_int(raw, "strong_rssi_threshold"),
        close_rssi_threshold=_required_int(raw, "close_rssi_threshold"),
        min_packets=_required_int(raw, "min_packets"),
        window_sec=_required_int(raw, "window_sec"),
        clear_sec=_required_int(raw, "clear_sec"),
        cooldown_sec=_required_int(raw, "cooldown_sec"),
    )


def _required_mapping(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw[key]
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be a mapping")
    return value


def _required_list(raw: dict[str, Any], key: str) -> list[Any]:
    value = raw[key]
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list")
    return value


def _required_str(raw: dict[str, Any], key: str) -> str:
    value = raw[key]
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


def _required_int(raw: dict[str, Any], key: str) -> int:
    value = raw[key]
    return int(value)
