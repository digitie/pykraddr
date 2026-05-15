# 주소 DB 스키마와 유지보수 메모

이 문서는 이후 Codex 세션과 라이브러리 유지보수자가 가장 먼저 참고할 스키마
메모입니다. Juso 상세 페이지의 "도로명주소 한글" 스키마, 사용자가 제공한
`주소 코드 데이터 구조 및 API 정보.pdf`, 실제 적재 검증 결과를 기준으로
정리했습니다.

## 문서 작성 원칙

이 저장소의 문서와 코드 docstring은 한글로 작성합니다. API 엔드포인트, 컬럼명,
테이블명, 클래스명, 환경 변수, 명령어, URL처럼 원문 유지가 필요한 기술 식별자는
그대로 둡니다. 새 문서나 docstring을 추가할 때도 같은 원칙을 따릅니다.

## 설계 목표

- 공급자 TXT 컬럼은 손실 없이 보존합니다.
- 매번 계산하기 비싼 식별자 조각은 파생 컬럼으로 저장합니다.
- SQLAlchemy 2 Core 테이블과 명시적 인덱스를 사용합니다.
- SQLite는 기본 내장 저장소로 유지하되, PostGIS 확장이 필요한 공간 데이터는
  PostgreSQL/PostGIS에 분리합니다.
- 월 전체분은 기준 스냅샷으로 보고, 일변동 자료는 변동 사유 코드에 따라
  증분 반영합니다.
- 공급자 식별자 이력을 보존하고, 임의 로컬 대체키를 만들지 않습니다.

## 핵심 식별자

### 법정동코드

`legal_dong_code`는 토지, 지적, 건축물, 주소 데이터가 함께 사용하는 10자리
법정동 식별자입니다.

| 구간 | 의미 | 예시 |
| --- | --- | --- |
| 1-2 | 시도 | `11` |
| 3-5 | 시군구 | `11110`의 `110` |
| 6-8 | 읍면동 | `11110101`의 `101` |
| 9-10 | 리 | 없으면 `00` |

저장소는 다음 파생 컬럼을 만듭니다.

- `sido_code`: 앞 2자리
- `sigungu_code`: 앞 5자리
- `eup_myeon_dong_code`: 앞 8자리
- `ri_code`: 마지막 2자리

전국 단위 테이블에서 지역 조회를 할 때는 우선 `sigungu_code`로 범위를 좁히는
것이 좋습니다.

### PNU

`pnu`는 19자리 필지번호이며 지번/지적 데이터의 안정적인 조인 키입니다.

```text
PNU = legal_dong_code(10) + mountain_yn(1) + lot_main_no(4) + lot_sub_no(4)
```

구현 규칙:

- `lot_main_no`와 `lot_sub_no`는 4자리로 0 채움합니다.
- 비어 있는 지번 번호는 `0000`으로 저장합니다.
- `mountain_yn`은 원본 값이 비어 있을 때만 `0`으로 보정합니다.

예시:

```text
legal_dong_code=1111010100, mountain_yn=0, lot_main_no=1, lot_sub_no=0
PNU=1111010100000010000
```

### 도로명주소 관리번호

`road_address_management_number`는 26자리 도로명주소/건물 관리번호입니다. 검색
API에서는 같은 식별자를 `bdMgtSn`으로 받으므로, 저장소는
`building_management_number`도 별칭 컬럼으로 채웁니다.

일반 구조:

| 구간 | 의미 |
| --- | --- |
| 1-8 | 법정동 상위 코드: 시도 + 시군구 + 읍면동 |
| 9-15 | 도로 번호 |
| 16 | 위치 코드: 지상, 지하, 공중, 수상 등 |
| 17-21 | 건물 본번, 0 채움 |
| 22-26 | 건물 부번, 0 채움 |

공급자 TXT 스키마는 복합 키를 표시하므로 kraddr.geo도 다음 복합 기본키를
유지합니다.

```text
road_address_management_number
road_name_code
underground_yn
building_main_no
building_sub_no
```

실무 조회에서는 26자리 관리번호가 주 식별자로 쓰이므로 별도 인덱스도 둡니다.

### 도로명코드

`road_name_code`는 12자리 도로 식별자입니다.

| 구간 | 의미 |
| --- | --- |
| 1-5 | 시군구 코드 |
| 6-12 | 도로 번호 |

저장소는 다음 값을 파생합니다.

- `road_sigungu_code`: 앞 5자리
- `road_number`: 뒤 7자리

## 테이블

### PostGIS 법정동/GIS 스키마

PostgreSQL/PostGIS 지원은 `kraddr.geo.postgis`에 있으며, 로컬 GIS 작업은 WSL2에서
실행하는 것을 기준으로 검증했습니다.

WSL2 설치 예시:

```bash
cd /mnt/f/dev/python-kraddr-geo
python3 -m venv ~/.cache/kraddr-geo-venv
source ~/.cache/kraddr-geo-venv/bin/activate
python -m pip install -e ".[dev,postgis]"
```

PostGIS 스키마 구성:

- `legal_dong_codes`: data.go.kr/code.go.kr 법정동코드 마스터 테이블
- `legal_dong_code_aliases`: 소스별 코드 차이를 CSV 마스터 코드에 연결하는 별칭
  테이블
- `legal_dong_boundaries`: SHP 경계 테이블, `geom MULTIPOLYGON(5179)`
- `legal_dong_boundary_mapping_issues`: 누락/폐지 코드 검토용 뷰
- `road_address_points`: Juso 내비게이션용DB 주소점 테이블

경계 FK:

```text
legal_dong_boundaries.legal_dong_code
  -> legal_dong_codes.legal_dong_code
```

CSV가 마스터입니다. 예를 들어 VWorld/N3A는 세종특별자치시 시도 경계에
`3600000000`을 쓰지만, code.go.kr/data.go.kr 법정동 마스터는 `3611000000`을
사용합니다. 로더는 이 차이를 `legal_dong_code_aliases`로 해석합니다.

```text
source_system=vworld_n3a
source_layer=sido
source_code=3600000000
legal_dong_code=3611000000
```

원본 SHP 코드는 `source_code`에 보존하고, 매핑 상태는 `mapping_status`에
기록합니다. 별칭 매핑 행은 CSV 마스터 테이블을 오염시키지 않으면서 유효한 FK를
유지합니다.

대량 적재 방식:

- 법정동 CSV: `psycopg` COPY
- SHP ZIP: GeoPandas/pyogrio 읽기 경로
- 경계 쓰기: `GeoDataFrame.to_postgis(..., chunksize=...)`
- 공간 인덱스: GeoAlchemy2가 만드는 PostGIS GiST 인덱스

WSL2 명령과 검증 결과는
[legal-dong-postgis-report.md](legal-dong-postgis-report.md)를 참고하세요.

### `road_address_points`

이 선택 테이블은 Juso 내비게이션용DB 건물정보 행을 주소점으로 저장합니다.

기본키:

```text
building_management_number
```

주요 컬럼:

```text
legal_dong_code
road_name_code
underground_yn
building_main_no
building_sub_no
postal_code
road_address
building_name
x
y
coordinate_source
change_reason_code
geom geometry(Point, 5179)
```

`coordinate_source`는 공급자 행에 출입구 좌표가 있으면 `entrance`, 출입구 좌표가
없어서 건물 중심 좌표를 사용하면 `center`입니다. 이 값은 원천 구분용 코드이므로
영문 값을 유지합니다.

최근접 도로명주소 리버스 지오코딩은 다음 형태의 질의를 사용합니다.

```sql
ORDER BY geom <-> ST_Transform(ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), 5179)
LIMIT 1
```

이 테이블은 필지 폴리곤과 분리합니다. `road_address_points`는 "가장 가까운
도로명주소점"을 답하고, "이 좌표가 포함된 필지"를 답하지 않습니다.

### `road_name_addresses`

"도로명주소 한글" 마스터 행을 저장합니다.

기본키:

```text
road_address_management_number
road_name_code
underground_yn
building_main_no
building_sub_no
```

원본 컬럼:

```text
road_address_management_number
legal_dong_code
sido_name
sigungu_name
legal_eup_myeon_dong_name
legal_ri_name
mountain_yn
lot_main_no
lot_sub_no
road_name_code
road_name
underground_yn
building_main_no
building_sub_no
administrative_dong_code
administrative_dong_name
postal_code
previous_road_name_address
effective_date
apartment_yn
change_reason_code
building_register_name
sigungu_building_name
remark
```

파생 컬럼:

```text
building_management_number
sido_code
sigungu_code
eup_myeon_dong_code
ri_code
road_sigungu_code
road_number
pnu
```

인덱스:

```text
ix_road_name_addresses_mgmt_no
ix_road_name_addresses_building_mgmt
ix_road_name_addresses_legal_dong
ix_road_name_addresses_sigungu
ix_road_name_addresses_emd
ix_road_name_addresses_road_name
ix_road_name_addresses_road_lookup
ix_road_name_addresses_pnu
ix_road_name_addresses_postal_code
```

`ix_road_name_addresses_road_lookup`는 API 형태 조회에 맞춰 다음 조합을 덮습니다.

```text
road_name_code + underground_yn + building_main_no + building_sub_no
```

### `related_jibuns`

도로명주소 레코드에 연결된 관련 지번 행을 저장합니다.

기본키:

```text
road_address_management_number
legal_dong_code
mountain_yn
lot_main_no
lot_sub_no
```

이 테이블은 하나의 도로명주소를 연결된 모든 지번/PNU로 확장할 때 사용합니다.

### `sync_metadata`

ETL 상태를 저장하는 작은 키-값 테이블입니다.

```text
key
value
updated_at
```

자주 쓰는 키:

- `full_archive_path`
- `full_standard_date`
- `last_daily_date`
- `updated_at`

## ETL 흐름

### 월 전체분 적재

최신 "도로명주소 한글" 월 전체분 ZIP을 기준 스냅샷으로 사용합니다.

```python
from kraddr.geo import RoadNameAddressDataClient, RoadNameAddressStore

data = RoadNameAddressDataClient()
zip_path = data.download_latest_full("data/juso/full")

with RoadNameAddressStore("data/juso/rnaddrkor.sqlite") as store:
    counts = store.load_full_archive(zip_path, replace=True)
    print(counts)
```

`load_full_archive()` 동작:

- 필요하면 기존 행과 메타데이터를 삭제합니다.
- 도로명주소 마스터 행을 스트리밍합니다.
- 관련 지번 행을 스트리밍합니다.
- 배치 단위로 삽입 또는 갱신합니다.
- 법정동 조각, 도로명코드 조각, `pnu`, `building_management_number`를 파생합니다.
- 전체분 적재 메타데이터를 기록합니다.

### 일별 증분 갱신

일변동 파일은 변동 사유 코드 기반 델타입니다.

| 코드 | 의미 | 저장소 동작 |
| --- | --- | --- |
| `31` | 신규 | 삽입 또는 갱신 |
| `34` | 변경 | 삽입 또는 갱신 |
| `63` | 삭제 | 공급자 기본키로 삭제 |

```python
from datetime import date

paths = data.download_daily_changes(
    "data/juso/daily",
    start=date(2026, 4, 1),
    end=date(2026, 5, 6),
)

with RoadNameAddressStore("data/juso/rnaddrkor.sqlite") as store:
    for path in paths:
        print(path, store.apply_daily_archive(path))
```

실제 테스트에서 확인한 동작:

- 일부 일변동 ZIP 멤버는 `No Data`만 포함합니다. 파서는 이 멤버를 건너뜁니다.
- `archive_standard_date()`는 먼저 압축 파일명, 그다음 내부 멤버명에서 날짜를
  찾습니다.
- 날짜를 추정할 수 있을 때만 `last_daily_date`를 갱신합니다.

## 조회 패턴

공급자 복합 기본키 조회:

```python
row = store.get_road_address(
    (
        "1111010100100010000000001",
        "111102005001",
        "0",
        "1",
        "0",
    )
)
```

26자리 관리번호 조회:

```python
rows = store.get_road_addresses_by_management_number("1111010100100010000000001")
```

PNU 필지 조인:

```python
road_rows = store.find_road_addresses_by_pnu("1111010100000010000")
jibun_rows = store.find_related_jibuns_by_pnu("1111010100000010000")
```

지역 필터는 `sigungu_code`나 `eup_myeon_dong_code`에서 시작하는 것이 좋습니다.
전국 테이블에서 표시 이름만으로 먼저 필터링하지 않습니다.

## 기존 SQLite 업그레이드

이전 버전이 만든 SQLite DB를 열면 `RoadNameAddressStore`가 누락된 파생 컬럼과
인덱스를 추가합니다. 다만 이전 버전으로 이미 적재된 행은 전체 재적재 또는
backfill 전까지 파생 컬럼이 비어 있을 수 있습니다.

다시 내려받지 않고 채우기:

```python
from kraddr.geo import RoadNameAddressStore

with RoadNameAddressStore("data/juso/rnaddrkor.sqlite") as store:
    store.backfill_derived_columns()
```

운영용 재구축은 최신 월 전체분을 다시 적재하고, 그 이후 일변동 파일을 순서대로
재생하는 방식을 권장합니다.

## Codex 유지보수 체크리스트

1. 테이블 컬럼을 바꾸기 전에 `src/kraddr/geo/data.py`를 먼저 읽습니다.
2. 파서 컬럼 순서는 공식 TXT 스키마와 정확히 일치해야 합니다.
3. 코드는 앞 0이 중요하므로 공급자 컬럼은 문자열로 보관합니다.
4. `pnu`도 숫자가 아니라 식별자 문자열입니다.
5. 공급자 복합 기본키를 제거하려면 중복 분석과 마이그레이션 계획을 함께
   작성합니다.
6. 조회 헬퍼를 추가할 때는 Python 필터링보다 인덱스를 우선 고려합니다.
7. 일변동 동작을 바꿀 때는 `31`, `34`, `63`, `No Data` 멤버를 모두 테스트합니다.
8. 문서와 docstring은 한글로 작성합니다. 기술 식별자만 원문을 유지합니다.
9. `data/`는 커밋하지 않습니다. 실제 SQLite DB는 GB 단위입니다.
10. 푸시 전에는 다음 검사를 실행합니다.

```powershell
python -m ruff check .
python -m pytest
python -m mypy src/kraddr/geo
```

2026년 5월 구현 당시 실적:

```text
최신 전체분: 202603_도로명주소 한글_전체분.zip
전체 도로명주소 행: 6,416,637
전체 관련 지번 행: 1,769,370
적용한 일변동 범위: 2026-04-01부터 2026-05-06까지
최종 도로명주소 행: 6,418,735
최종 관련 지번 행: 1,770,362
last_daily_date: 2026-05-06
```
