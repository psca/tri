from tri_timing.ibeacon import parse_ibeacon_manufacturer_data


def test_parse_ibeacon_manufacturer_data_decodes_uuid_major_minor_power() -> None:
    payload = bytes.fromhex(
        "0215"
        "11111111111111111111111111111111"
        "0001"
        "0002"
        "c5"
    )

    result = parse_ibeacon_manufacturer_data({0x004C: payload})

    assert result is not None
    assert result.uuid == "11111111-1111-1111-1111-111111111111"
    assert result.major == 1
    assert result.minor == 2
    assert result.measured_power == -59


def test_parse_ibeacon_manufacturer_data_ignores_non_ibeacon_payload() -> None:
    assert parse_ibeacon_manufacturer_data({0x004C: b"\x01\x02short"}) is None
    assert parse_ibeacon_manufacturer_data({0x1234: b"\x02\x15" + bytes(21)}) is None
