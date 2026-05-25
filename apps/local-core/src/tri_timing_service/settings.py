from dataclasses import dataclass
import os
from pathlib import Path
from tempfile import gettempdir


@dataclass(frozen=True)
class ServiceSettings:
    race_config_path: Path
    athletes_path: Path
    database_path: Path
    cloud_sync_endpoint: str | None = None
    cloud_sync_token: str | None = None
    cloud_sync_interval_sec: float = 5.0

    @classmethod
    def from_env(cls) -> "ServiceSettings":
        return cls(
            race_config_path=Path(os.environ.get("TRI_RACE_CONFIG", "race.yaml")),
            athletes_path=Path(os.environ.get("TRI_ATHLETES", "athletes.csv")),
            database_path=Path(os.environ.get("TRI_DATABASE", "tri-timing.sqlite")),
            cloud_sync_endpoint=os.environ.get("TRI_CLOUD_SYNC_ENDPOINT"),
            cloud_sync_token=os.environ.get("TRI_CLOUD_SYNC_TOKEN"),
            cloud_sync_interval_sec=float(
                os.environ.get("TRI_CLOUD_SYNC_INTERVAL_SEC", "5")
            ),
        )

    @classmethod
    def for_tests(cls) -> "ServiceSettings":
        return cls(
            race_config_path=Path("tests/fixtures/race.yaml"),
            athletes_path=Path("tests/fixtures/athletes.csv"),
            database_path=Path(gettempdir()) / "tri-timing-test.sqlite",
        )
