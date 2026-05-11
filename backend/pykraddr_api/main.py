"""주소 탐색 웹 API."""

from __future__ import annotations

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from .database import health, list_addresses

app = FastAPI(title="pykraddr 주소 탐색 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3010",
        "http://127.0.0.1:3010",
    ],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/health")
def get_health() -> dict[str, object]:
    """백엔드와 PostGIS 상태를 반환한다."""

    return health()


@app.get("/addresses")
def get_addresses(
    query: str = "",
    scope: str = Query("all", pattern="^(all|road|jibun|code)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> dict[str, object]:
    """주소 목록을 페이지 단위로 반환한다."""

    return list_addresses(query=query, scope=scope, page=page, page_size=page_size)
