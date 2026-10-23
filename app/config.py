"""Settings, read from the environment and from .env (which is never committed)."""
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _flag(name, default="false"):
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    zetaris_rest_url: str
    zetaris_org_id: str
    zetaris_api_key: str = field(repr=False)
    meterless_base_url: str
    meterless_runtime_token: str = field(repr=False)
    meterless_model: str
    sample_mode: bool
    logs_dir: Path
    state_dir: Path
    output_dir: Path
    sample_dir: Path


def load_settings(*, sample_mode=None):
    return Settings(
        zetaris_rest_url=os.environ.get("ZETARIS_REST_URL", "http://localhost:8888/api/v1.0"),
        zetaris_org_id=os.environ.get("ZETARIS_ORG_ID", "1"),
        zetaris_api_key=os.environ.get("ZETARIS_API_KEY", ""),
        meterless_base_url=os.environ.get("METERLESS_BASE_URL", "http://127.0.0.1:8088/v1"),
        meterless_runtime_token=os.environ.get("METERLESS_RUNTIME_TOKEN", ""),
        meterless_model=os.environ.get("METERLESS_MODEL", "nvidia/nemotron-3.5-lightning-30b-a3b"),
        sample_mode=_flag("SAMPLE_MODE") if sample_mode is None else sample_mode,
        logs_dir=ROOT / "logs",
        state_dir=ROOT / "state",
        output_dir=ROOT / "output",
        sample_dir=ROOT / "data" / "sample",
    )
