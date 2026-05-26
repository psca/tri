from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


APPLE_COMPANY_ID = 0x004C
IBEACON_PREFIX = b"\x02\x15"
IBEACON_PAYLOAD_LENGTH = 23


@dataclass(frozen=True)
class IBeaconAdvertisement:
    uuid: str
    major: int
    minor: int
    measured_power: int


def parse_ibeacon_manufacturer_data(
    manufacturer_data: dict[int, bytes],
) -> IBeaconAdvertisement | None:
    payload = manufacturer_data.get(APPLE_COMPANY_ID)
    if payload is None:
        return None
    if len(payload) != IBEACON_PAYLOAD_LENGTH:
        return None
    if not payload.startswith(IBEACON_PREFIX):
        return None

    return IBeaconAdvertisement(
        uuid=str(UUID(bytes=payload[2:18])),
        major=int.from_bytes(payload[18:20], byteorder="big"),
        minor=int.from_bytes(payload[20:22], byteorder="big"),
        measured_power=int.from_bytes(payload[22:23], byteorder="big", signed=True),
    )
