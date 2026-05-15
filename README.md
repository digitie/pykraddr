# python-kraddr-geo

`kraddr.geo`는 대한민국 Juso 도로명주소 API와
`business.juso.go.kr`에서 내려받을 수 있는 "도로명주소 한글" TXT 자료를
다루는 비공식 Python 라이브러리입니다.

외부 시스템에서는 REST 서버가 아니라 Python 패키지로 import해서 사용하는 것을
기준으로 둡니다. 팝업 API는 의도적으로 감싸지 않으며, Juso 검색 클라이언트,
다운로드 자료 파싱, PostgreSQL/PostGIS 적재, 경계/주소점 조회, fixture 기반
회귀 테스트 흐름에 집중합니다.

## 문서 작성 원칙

이 저장소의 설명 문서와 코드 docstring은 한글로 작성합니다. API 엔드포인트,
환경 변수, 테이블명, 컬럼명, 클래스명, 명령어, URL처럼 원문 그대로 유지해야
하는 기술 식별자는 예외입니다.

## 검색 API

```python
from kraddr.geo import KrAddrClient

client = KrAddrClient.from_env("JUSO_CONFM_KEY")

page = client.search("세종대로 110", add_info=True)
first = page.items[0]
print(first.road_address, first.zip_code, first.administrative_code)

coords = client.coordinates(
    administrative_code=first.administrative_code,
    road_name_code=first.road_name_code,
    underground_yn=first.underground_yn,
    building_main_no=first.building_main_no,
    building_sub_no=first.building_sub_no or 0,
)
print(coords.items[0].x, coords.items[0].y)
```

구현된 엔드포인트:

- `addrLinkApi.do`: 도로명주소 검색
- `addrEngApi.do`: 영문주소 검색
- `addrCoordApi.do`: 좌표 검색
- `addrDetailApi.do`: 상세주소 검색
- 지도 API 가이드/소스 ZIP 다운로드 헬퍼

## 도로명주소 한글 자료

PostgreSQL 드라이버가 필요하면 다음 extra를 설치합니다.

```bash
python -m pip install "python-kraddr-geo[postgres]"
```

```python
from kraddr.geo import RoadNameAddressDataClient, RoadNameAddressStore

POSTGRES_URL = "postgresql+psycopg://postgres:postgres@localhost:55433/kraddr_geo"

data = RoadNameAddressDataClient()
zip_path = data.download_latest_full("data/juso")

with RoadNameAddressStore(POSTGRES_URL) as store:
    store.load_full_archive(zip_path, replace=True)
    print(store.count_road_addresses())
```

일변동 자료는 Juso 변동 사유 코드를 기준으로 반영합니다.

- `31`: 신규
- `34`: 변경
- `63`: 삭제

```python
from datetime import date

paths = data.download_daily_changes(
    "data/juso/daily",
    start=date(2026, 4, 1),
    end=date(2026, 4, 30),
)

with RoadNameAddressStore(POSTGRES_URL) as store:
    for path in paths:
        store.apply_daily_archive(path)
```

`RoadNameAddressStore`는 SQLAlchemy 2 Core를 사용하며 운영 기준 저장소는
PostgreSQL입니다. 기존 SQLAlchemy `Engine`이나 SQLAlchemy URL을 직접 넘길 수
있습니다. 공식 TXT 컬럼을 보존하고, `sigungu_code`, `road_number`,
`building_management_number`, `pnu` 같은 조회용 파생 키를 추가로 인덱싱합니다.
SQLite 파일 경로는 테스트와 이전 버전 호환을 위해서만 유지합니다.

자주 쓰는 조회 헬퍼:

```python
rows = store.get_road_addresses_by_management_number("1111010100100010000000001")
parcel_rows = store.find_road_addresses_by_pnu("1111010100000010000")
```

최적화된 SQLAlchemy 스키마, 식별자 구조, ETL 흐름, 유지보수 메모는
[docs/address-db-schema.md](docs/address-db-schema.md)를 참고하세요.
코드를 처음 읽는 사람을 위한 전체 흐름 안내는
[docs/code-guide-for-beginners.md](docs/code-guide-for-beginners.md)에 정리했습니다.

## DebugRun과 fixture replay

디버그 UI나 외부 도구는 라이브러리의 `debug_*()` 메서드를 호출해 원본 요청,
원본 응답, parsed result, processed result를 한 번에 받을 수 있습니다.

```python
from kraddr.geo import KrAddrClient, save_fixture

client = KrAddrClient.from_env("JUSO_CONFM_KEY")
run = client.debug_search("세종대로 110", add_info=True)

save_fixture(
    base_dir="tests/fixtures",
    function_name=run.function,
    case_name="search_sejong_normal",
    description="세종대로 정상 검색 케이스",
    input_data=run.input,
    request_data=run.request,
    response_data=run.response,
    parsed_result=run.parsed,
    processed_result=run.processed,
)
```

fixture JSON에는 API key와 토큰 계열 값이 저장되지 않습니다. 기본 테스트는
`tests/fixtures/**/*.json`을 읽어 외부 API 호출 없이 raw response를 parser와
processor에 다시 넣는 replay 방식으로 동작합니다.

## React 웹 UI

주소 탐색과 지도 표시를 위한 Next.js/Tailwind CSS 앱은 `web/` 디렉터리에 있고,
문서에 있던 Streamlit 앱은 추가하지 않습니다. `backend/`는 React 화면을 로컬에서
확인하기 위한 선택 어댑터이며, 이 패키지의 외부 사용 방식은 Python 라이브러리
import입니다.

```bash
cd backend
uvicorn kraddr_geo_api.main:app --app-dir . --host 0.0.0.0 --port 3011 --reload

cd web
npm install
npm run dev
```

WSL 실행 기준 포트는 프론트엔드 `3010`, 백엔드 `3011`입니다. 브라우저 주소는
Kakao JavaScript SDK 도메인 등록과 맞추기 위해 `http://localhost:3010`을
기본으로 사용합니다.

웹 UI는 다음 흐름을 제공합니다.

- `샘플 탐색`: 프론트엔드와 지도 표시를 빠르게 확인하는 내장 샘플
- `전체 목록`: PostGIS `address_serving_juso_road_address` 테이블을 페이지 단위로 조회
- 검색 범위: 전체, 도로명, 지번, 코드
- 목록 표시 개수: `5`, `10`, `20`, `50`, `100`개
- 기본 표시 개수: `10`개
- 표시 개수 저장: `kraddr_geo_page_size` 쿠키
- 처리 중 상태: 목록 조회 중 회전 아이콘과 `처리 중` 배지 표시

Kakao 지도 표시에는 `NEXT_PUBLIC_KAKAO_JAVASCRIPT_KEY`가 필요합니다. 실제 키는
`web/.env.local`처럼 Git에서 무시되는 파일에만 둡니다. 자세한 내용은
[web/README.md](web/README.md)와 [backend/README.md](backend/README.md)를 참고하세요.

## 법정동코드와 PostGIS 경계

PostGIS/GIS 적재 기능은 선택 의존성으로 제공됩니다.

```bash
python -m pip install "python-kraddr-geo[postgis]"
```

```python
from pathlib import Path
from kraddr.geo.postgis import PostGISLegalDongStore

url = "postgresql+psycopg://postgres:postgres@localhost:55433/kraddr_geo"

with PostGISLegalDongStore(url, schema="kraddr") as store:
    store.create_schema()
    store.load_legal_dong_csv(Path("dataset/국토교통부_법정동코드_20250805.csv"))
    result = store.load_boundary_zips(sorted(Path("dataset").glob("N3A_*.zip")))
    print(result)
```

PostGIS 로더는 법정동 CSV에 `psycopg` COPY를 사용하고, SHP ZIP 경계 적재에는
GeoPandas와 GeoAlchemy2를 사용합니다. 법정동코드의 기준은 CSV 마스터입니다.
VWorld/N3A의 세종특별자치시 시도 경계 코드 `3600000000`처럼 소스별 코드가
마스터와 다를 때는 `legal_dong_code_aliases` 별칭 테이블로 처리합니다.

WSL2 검증 보고서는
[docs/legal-dong-postgis-report.md](docs/legal-dong-postgis-report.md)에 있고,
지오코딩/리버스 지오코딩 준비 상태는
[docs/geocoding-readiness.md](docs/geocoding-readiness.md)에 정리되어 있습니다.

## 리버스 지오코딩

좌표에서 도로명주소를 얻는 기능은 오프라인 우선 방식입니다.

```python
from kraddr.geo import ReverseGeocoder, RoadAddressPointStore, VWorldReverseGeocoder

url = "postgresql+psycopg://postgres:postgres@localhost:55433/kraddr_geo"

with RoadAddressPointStore(url, schema="kraddr") as store:
    store.load_navigation_building_archive("dataset/navigation_building.zip")
    geocoder = ReverseGeocoder(
        offline_store=store,
        vworld=VWorldReverseGeocoder.from_env(),
        max_offline_distance_m=50,
    )
    result = geocoder.reverse_road_address(lon=127.1013, lat=37.4023)
    print(result.road_address if result else None)
```

오프라인 테이블은 Juso 내비게이션용DB 건물정보 TXT 좌표를 사용합니다. 오프라인
저장소가 없거나 가까운 주소점이 없으면 `python-vworld-api`를 통해 VWorld Geocoder API
2.0을 호출할 수 있습니다. 자세한 설계는
[docs/reverse-geocoding.md](docs/reverse-geocoding.md)를 참고하세요.

TXT 파서는 직접 사용할 수도 있습니다.

```python
from kraddr.geo import iter_road_name_address_records

for record in iter_road_name_address_records(zip_path):
    print(record.road_address_management_number, record.road_name)
    break
```
