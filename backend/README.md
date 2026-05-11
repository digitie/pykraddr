# pykraddr 백엔드

`backend` 디렉터리는 주소 목록 브라우징과 GIS 경계 조회를 위한 FastAPI 서버입니다. 기본 기준은 PostgreSQL + PostGIS + SQLAlchemy 2 + GeoAlchemy2이며, 경계 GeoJSON을 화면용 좌표로 정리할 때 Shapely를 사용합니다. GeoPandas는 같은 GIS 처리 스택의 필수 의존성으로 설치하고 상태 점검에서 버전을 확인합니다.

## 실행 포트

- 백엔드: `3011`
- 프론트엔드: `3010`

## WSL 실행

```bash
cd /mnt/f/dev/pykraddr
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
export PYKRADDR_DATABASE_URL="postgresql+psycopg://사용자:비밀번호@localhost:55432/tripmate"
export PYKRADDR_DB_SCHEMA="public"
uvicorn pykraddr_api.main:app --app-dir backend --host 0.0.0.0 --port 3011 --reload
```

로컬 비밀번호는 `backend/.env.local` 같은 무시되는 파일이나 셸 환경 변수로만 관리합니다. 저장소에는 실제 접속 문자열을 커밋하지 않습니다.

## API

- `GET /health`: DB 연결, PostGIS, 주요 GIS 라이브러리 버전을 확인합니다.
- `GET /addresses`: 도로명주소 목록을 페이지 단위로 조회합니다.

`/addresses` 주요 쿼리:

- `query`: 도로명, 지번, 법정동코드, 도로명코드, PNU 성격의 검색어
- `scope`: `all`, `road`, `jibun`, `code`
- `page`: 1부터 시작
- `page_size`: 최대 100

주소 좌표는 개별 건물 좌표가 아니라 PostGIS 법정동/시군구/시도 경계의 `ST_PointOnSurface` 결과입니다. 정확한 건물 출입구 좌표가 필요한 경우 별도의 주소점 테이블을 추가로 적재해서 조인해야 합니다.
