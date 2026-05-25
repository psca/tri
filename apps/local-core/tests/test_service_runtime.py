from pathlib import Path

from tri_timing_service.settings import ServiceSettings


def test_service_settings_defaults_to_fixture_paths() -> None:
    settings = ServiceSettings.for_tests()

    assert settings.race_config_path == Path("tests/fixtures/race.yaml")
    assert settings.athletes_path == Path("tests/fixtures/athletes.csv")
    assert settings.database_path.name == "tri-timing-test.sqlite"
