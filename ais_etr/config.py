from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
from typing import Iterable


PILOT_DISTRICTS = ("พังโคน", "วาริชภูมิ", "นิคมน้ำอูน")


def load_env_file(path: str | Path = ".env") -> None:
    """Load simple KEY=VALUE lines into os.environ if not already set."""
    env_path = Path(path)
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _split_csv(value: str | None, default: Iterable[str]) -> tuple[str, ...]:
    if not value:
        return tuple(default)
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() not in {"0", "false", "no"}


@dataclass(frozen=True)
class Settings:
    workspace: Path = field(default_factory=lambda: Path.cwd())
    db_path: Path = field(default_factory=lambda: Path("runtime/ais_etr.sqlite"))
    registry_path: Path = field(default_factory=lambda: Path("upstream_result.xlsx"))
    event_file: Path = field(default_factory=lambda: Path("Event_from_report52_PKN.xlsx"))
    distance_file: Path = field(default_factory=lambda: Path("gis_distance.csv"))
    planned_outage_file: Path = field(
        default_factory=lambda: Path("PEA_ReportPO_planned_outage_transformer_2026_complete.csv")
    )
    planned_notice_min_days: int = 3
    planned_require_asset_match: bool = True
    etr_files: tuple[Path, ...] = field(
        default_factory=lambda: (
            Path("ETR_PKN_2024.xlsx"),
            Path("ETR_PKN_2025.xlsx"),
            Path("ETR_PKN_2026_6M.xlsx"),
        )
    )
    model_path: Path = field(default_factory=lambda: Path("runtime/model_quantiles.json"))
    webex_api_base: str = "https://webexapis.com/v1"
    webex_auth_mode: str = "bot"
    webex_bot_token: str | None = None
    webex_room_id: str | None = None
    webex_room_district: str | None = None
    webex_require_mention: bool = True
    webex_client_id: str | None = None
    webex_client_secret: str | None = None
    webex_integration_id: str | None = None
    webex_authorization_url: str = "https://webexapis.com/v1/authorize"
    webex_redirect_uri: str = "http://127.0.0.1:8765/oauth/callback"
    webex_scopes: tuple[str, ...] = ("spark:rooms_read", "spark:messages_read")
    webex_token_path: Path = field(default_factory=lambda: Path("runtime/webex_oauth_token.json"))
    line_channel_secret: str | None = None
    line_channel_access_token: str | None = None
    line_allowed_group_ids: tuple[str, ...] = ()
    line_allowed_chat_hashes: tuple[str, ...] = ()
    line_capture_mode: str = "shadow"
    notification_mode: str = "shadow"
    mock_webhook_url: str | None = None
    ais_inbound_api_key: str | None = None
    ais_callback_url: str | None = None
    pilot_districts: tuple[str, ...] = PILOT_DISTRICTS

    @classmethod
    def from_env(cls, env_path: str | Path = ".env") -> "Settings":
        load_env_file(env_path)
        return cls(
            workspace=Path(os.environ.get("AIS_ETR_WORKSPACE", Path.cwd())),
            db_path=Path(os.environ.get("AIS_ETR_DB", "runtime/ais_etr.sqlite")),
            registry_path=Path(os.environ.get("AIS_REGISTRY_XLSX", "upstream_result.xlsx")),
            event_file=Path(os.environ.get("AIS_EVENT_XLSX", "Event_from_report52_PKN.xlsx")),
            distance_file=Path(os.environ.get("AIS_DISTANCE_CSV", "gis_distance.csv")),
            planned_outage_file=Path(
                os.environ.get(
                    "AIS_PLANNED_OUTAGE_CSV",
                    "PEA_ReportPO_planned_outage_transformer_2026_complete.csv",
                )
            ),
            planned_notice_min_days=int(os.environ.get("AIS_PLANNED_NOTICE_MIN_DAYS", "3")),
            planned_require_asset_match=_env_bool("AIS_PLANNED_REQUIRE_ASSET_MATCH", True),
            etr_files=tuple(
                Path(item)
                for item in _split_csv(
                    os.environ.get("AIS_ETR_FILES"),
                    ("ETR_PKN_2024.xlsx", "ETR_PKN_2025.xlsx", "ETR_PKN_2026_6M.xlsx"),
                )
            ),
            model_path=Path(os.environ.get("AIS_ETR_MODEL", "runtime/model_quantiles.json")),
            webex_api_base=os.environ.get("WEBEX_API_BASE", "https://webexapis.com/v1"),
            webex_auth_mode=os.environ.get("WEBEX_AUTH_MODE", "bot").strip().lower(),
            webex_bot_token=os.environ.get("WEBEX_BOT_TOKEN"),
            webex_room_id=os.environ.get("WEBEX_ROOM_ID"),
            webex_room_district=os.environ.get("WEBEX_ROOM_DISTRICT"),
            webex_require_mention=os.environ.get("WEBEX_REQUIRE_MENTION", "true").lower()
            not in {"0", "false", "no"},
            webex_client_id=os.environ.get("WEBEX_CLIENT_ID"),
            webex_client_secret=os.environ.get("WEBEX_CLIENT_SECRET"),
            webex_integration_id=os.environ.get("WEBEX_INTEGRATION_ID"),
            webex_authorization_url=os.environ.get("WEBEX_AUTHORIZATION_URL", "https://webexapis.com/v1/authorize"),
            webex_redirect_uri=os.environ.get(
                "WEBEX_REDIRECT_URI",
                "http://127.0.0.1:8765/oauth/callback",
            ),
            webex_scopes=_split_scopes(
                os.environ.get("WEBEX_SCOPES"),
                ("spark:rooms_read", "spark:messages_read"),
            ),
            webex_token_path=Path(os.environ.get("WEBEX_TOKEN_PATH", "runtime/webex_oauth_token.json")),
            line_channel_secret=os.environ.get("LINE_CHANNEL_SECRET"),
            line_channel_access_token=os.environ.get("LINE_CHANNEL_ACCESS_TOKEN"),
            line_allowed_group_ids=_split_csv(os.environ.get("LINE_ALLOWED_GROUP_IDS"), ()),
            line_allowed_chat_hashes=_split_csv(os.environ.get("LINE_ALLOWED_CHAT_HASHES"), ()),
            line_capture_mode=os.environ.get("LINE_CAPTURE_MODE", "shadow"),
            notification_mode=os.environ.get("AIS_NOTIFICATION_MODE", "shadow"),
            mock_webhook_url=os.environ.get("AIS_MOCK_WEBHOOK_URL"),
            ais_inbound_api_key=os.environ.get("AIS_INBOUND_API_KEY"),
            ais_callback_url=os.environ.get("AIS_CALLBACK_URL"),
            pilot_districts=_split_csv(os.environ.get("AIS_PILOT_DISTRICTS"), PILOT_DISTRICTS),
        )

    def resolve(self, path: str | Path) -> Path:
        path = Path(path)
        if path.is_absolute():
            return path
        return self.workspace / path


def ensure_runtime_dirs(settings: Settings) -> None:
    settings.resolve(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    settings.resolve(settings.model_path).parent.mkdir(parents=True, exist_ok=True)
    settings.resolve(settings.webex_token_path).parent.mkdir(parents=True, exist_ok=True)


def _split_scopes(value: str | None, default: Iterable[str]) -> tuple[str, ...]:
    if not value:
        return tuple(default)
    if "," in value:
        return tuple(part.strip() for part in value.split(",") if part.strip())
    return tuple(part.strip() for part in value.split() if part.strip())
