from dataclasses import dataclass
from pathlib import Path
from tempfile import gettempdir


@dataclass(frozen=True)
class ServiceSettings:
    race_config_path: Path
    athletes_path: Path
    database_path: Path
    cloud_sync_endpoint: str | None = None
    cloud_sync_token: str | None = None

    @classmethod
    def for_tests(cls) -> "ServiceSettings":
        return cls(
            race_config_path=Path("tests/fixtures/race.yaml"),
            athletes_path=Path("tests/fixtures/athletes.csv"),
            database_path=Path(gettempdir()) / "tri-timing-test.sqlite",
        )
