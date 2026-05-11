"""웹 API 환경 설정."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    """백엔드 실행에 필요한 환경 설정."""

    database_url: str
    schema: str = "public"


def load_settings() -> Settings:
    """환경 변수에서 설정을 읽는다."""

    _load_local_env()
    database_url = os.environ.get("PYKRADDR_DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "PYKRADDR_DATABASE_URL 환경 변수가 필요합니다. "
            "PostgreSQL/PostGIS 접속 문자열을 설정하세요."
        )
    return Settings(
        database_url=database_url,
        schema=os.environ.get("PYKRADDR_DB_SCHEMA", "public"),
    )


def _load_local_env() -> None:
    """커밋하지 않는 로컬 환경 파일을 읽어 환경 변수 기본값으로 사용한다."""

    root = Path(__file__).resolve().parents[1]
    for path in (root / ".env.local", root / ".env"):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            text = line.strip()
            if not text or text.startswith("#") or "=" not in text:
                continue
            key, value = text.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
