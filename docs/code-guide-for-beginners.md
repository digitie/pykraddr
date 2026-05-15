# 처음 보는 사람을 위한 kraddr.geo 코드 안내서

작성일: 2026-05-10

이 문서는 Google Docs `주소 코드 데이터 구조 및 API 정보`의 내용을 바탕으로,
kraddr.geo 코드를 처음 읽는 사람이 주소 체계와 코드 구조를 함께 이해할 수 있도록
정리한 입문 문서입니다.

참고 원문:

- [주소 코드 데이터 구조 및 API 정보](https://docs.google.com/document/d/1SVSYdA2Ur5gWfscVRKP5bTkuYJ1Zy0nURhvo0MM3Cd0/edit?tab=t.0)

## 이 라이브러리가 하는 일

kraddr.geo는 대한민국 주소 데이터를 세 가지 방식으로 다룹니다.

1. Juso 검색 API를 호출합니다.
2. Juso와 data.go.kr에서 내려받은 대용량 TXT/CSV/ZIP 자료를 파싱합니다.
3. SQLite 또는 PostgreSQL/PostGIS에 적재해서 오프라인 주소 검색, 법정동 경계
   조회, 리버스 지오코딩의 기반 DB를 만듭니다.

처음 볼 때 중요한 관점은 "주소 문자열"보다 "식별자"입니다. 이 코드베이스는
사용자가 입력하는 주소 문자열을 직접 믿기보다, 국가 표준 식별자인 법정동코드,
PNU, 도로명주소 관리번호, 도로명코드를 기준으로 데이터를 정리합니다.

## 먼저 알아야 할 주소 식별자

### 법정동코드

법정동코드는 10자리 문자열입니다. 토지, 지적, 건축물, 주소 데이터가 공통으로
사용하는 가장 중요한 지역 기준 키입니다.

```text
법정동코드(10) = 시도(2) + 시군구(3) + 읍면동(3) + 리(2)
```

예를 들어 `1111010100`은 다음처럼 쪼개서 읽습니다.

| 구간 | 의미 | 값 |
| --- | --- | --- |
| 1-2 | 시도 | `11` |
| 1-5 | 시군구까지 | `11110` |
| 1-8 | 읍면동까지 | `11110101` |
| 9-10 | 리 | `00` |

코드 위치:

- `kraddr.geo.models.LegalDongRecord`
- `kraddr.geo.legal_dong.iter_legal_dong_records`
- `kraddr.geo.postgis.PostGISLegalDongStore`

### PNU

PNU는 필지 단위 식별자입니다. 지번 주소나 지적 폴리곤과 조인할 때 씁니다.

```text
PNU = 법정동코드(10) + 산여부(1) + 본번(4) + 부번(4)
```

예시:

```text
법정동코드 = 1111010100
산여부 = 0
본번 = 1 -> 0001
부번 = 0 -> 0000
PNU = 1111010100000010000
```

코드 위치:

- `kraddr.geo.store._pnu`
- `kraddr.geo.store._row_values`
- `RoadNameAddressStore.find_road_addresses_by_pnu`
- `RoadNameAddressStore.find_related_jibuns_by_pnu`

### 도로명주소 관리번호

도로명주소 관리번호는 건물/도로명주소를 식별하는 26자리 문자열입니다. Juso 검색
API에서는 `bdMgtSn`으로 오고, kraddr.geo 저장소에서는
`building_management_number` 별칭으로도 보관합니다.

일반 구조:

```text
도로명주소 관리번호(26)
= 법정동 상위 8자리
+ 도로번호 7자리
+ 위치 구분 1자리
+ 건물 본번 5자리
+ 건물 부번 5자리
```

코드 위치:

- `kraddr.geo.models.AddressSearchResult.building_management_number`
- `kraddr.geo.models.RoadNameAddressKoreanRecord.road_address_management_number`
- `kraddr.geo.store.ROAD_DERIVED_COLUMNS`

### 도로명코드

도로명코드는 12자리 문자열입니다.

```text
도로명코드(12) = 시군구코드(5) + 도로번호(7)
```

코드 위치:

- `kraddr.geo.store._road_code_values`
- `road_sigungu_code`
- `road_number`
- `ix_road_name_addresses_road_lookup`

## 패키지 전체 지도

```text
src/kraddr/geo/
  __init__.py      공개 API 모음
  _http.py         requests 세션, 재시도, HTTP 오류 변환
  exceptions.py    라이브러리 공통 예외
  models.py        API 응답과 TXT/CSV 행 모델
  client.py        Juso 검색 API 클라이언트
  data.py          도로명주소 한글 TXT/ZIP 다운로드와 파싱
  store.py         도로명주소 한글 SQLite 저장소와 일변동 반영
  legal_dong.py    법정동 CSV/API 파싱
  postgis.py       법정동 CSV와 SHP 경계의 PostGIS 적재
  reverse.py       주소점 적재와 리버스 지오코딩
```

처음 읽을 때는 다음 순서를 추천합니다.

1. `models.py`: 어떤 데이터가 오가는지 먼저 봅니다.
2. `data.py`: Juso TXT 파일을 어떻게 레코드로 바꾸는지 봅니다.
3. `store.py`: 레코드를 SQLite 테이블에 어떻게 넣는지 봅니다.
4. `legal_dong.py`: 법정동 CSV를 어떻게 표준 모델로 바꾸는지 봅니다.
5. `postgis.py`: 법정동/경계 데이터를 PostGIS에 어떻게 넣는지 봅니다.
6. `reverse.py`: 주소점과 VWorld 보조 호출이 어떻게 연결되는지 봅니다.
7. `client.py`: 온라인 Juso API 호출이 어떻게 모델로 변환되는지 봅니다.

## 주요 데이터 흐름

### 1. Juso 검색 API 호출

관련 파일:

- `client.py`
- `_http.py`
- `models.py`

흐름:

```text
KrAddrClient.search()
  -> _get_page()
  -> _http.response_json()
  -> _parse_page()
  -> AddressSearchResult.from_api()
```

예시:

```python
from kraddr.geo import KrAddrClient

client = KrAddrClient.from_env("JUSO_CONFM_KEY")
page = client.search("세종대로 110", add_info=True)
first = page.items[0]
print(first.road_address)
print(first.building_management_number)
```

이 흐름은 온라인 API 응답을 모델 객체로 바꾸는 경로입니다. 오프라인 DB 적재와는
분리되어 있습니다.

### 2. 도로명주소 한글 전체분 적재

관련 파일:

- `data.py`
- `models.py`
- `store.py`

흐름:

```text
RoadNameAddressDataClient.download_latest_full()
  -> ZIP 파일 다운로드
  -> iter_road_name_address_records()
  -> RoadNameAddressKoreanRecord
  -> RoadNameAddressStore.load_full_archive()
  -> road_name_addresses 테이블 upsert

iter_related_jibun_records()
  -> RelatedJibunRecord
  -> related_jibuns 테이블 upsert
```

테이블:

- `road_name_addresses`
- `related_jibuns`
- `sync_metadata`

이 흐름은 "전국 도로명주소 마스터 DB"를 만드는 작업입니다. 기본 저장소는
SQLite이며, 대용량이므로 `data/` 디렉터리는 커밋하지 않습니다.

### 3. 일변동 반영

관련 파일:

- `data.py`
- `store.py`

흐름:

```text
RoadNameAddressDataClient.download_daily_changes()
  -> 일변동 ZIP 목록 다운로드
  -> RoadNameAddressStore.apply_daily_archive()
  -> change_reason_code 기준 처리
```

변동 코드:

| 코드 | 의미 | 처리 |
| --- | --- | --- |
| `31` | 신규 | 삽입 또는 갱신 |
| `34` | 변경 | 삽입 또는 갱신 |
| `63` | 삭제 | 공급자 기본키로 삭제 |

처음 보는 사람이 놓치기 쉬운 점은 일변동 ZIP 안에 `No Data`만 있는 경우입니다.
파서는 이런 멤버를 정상적으로 건너뜁니다.

### 4. 법정동코드 CSV 적재

관련 파일:

- `legal_dong.py`
- `models.py`
- `postgis.py`

흐름:

```text
iter_legal_dong_records()
  -> LegalDongRecord
  -> PostGISLegalDongStore.load_legal_dong_csv()
  -> legal_dong_codes 테이블
```

`LegalDongRecord`는 10자리 법정동코드를 다음 파생 속성으로 나눕니다.

- `sido_code`
- `sigungu_code`
- `eup_myeon_dong_code`
- `ri_code`
- `legal_dong_level`

CSV가 마스터입니다. 코드베이스는 CSV에 없는 법정동코드를 임의로 만들지 않습니다.

### 5. SHP 경계 적재와 별칭 처리

관련 파일:

- `postgis.py`

흐름:

```text
PostGISLegalDongStore.load_boundary_zips()
  -> read_boundary_zip()
  -> source_code 추출
  -> resolve_legal_dong_code()
  -> legal_dong_boundaries 테이블
```

중요한 설계:

- 원본 SHP 코드는 `source_code`에 보존합니다.
- CSV 마스터에 매칭되는 코드는 `legal_dong_code`에 넣습니다.
- CSV 마스터와 소스 코드가 다르면 `legal_dong_code_aliases`로 해결합니다.

예시:

```text
VWorld/N3A 세종특별자치시 시도 경계 source_code = 3600000000
CSV/code.go.kr 법정동 마스터 legal_dong_code = 3611000000
```

이 경우 CSV 마스터에는 `3600000000`을 추가하지 않고, 별칭 테이블에만 다음 매핑을
둡니다.

```text
source_system = vworld_n3a
source_layer = sido
source_code = 3600000000
legal_dong_code = 3611000000
```

### 6. 리버스 지오코딩

관련 파일:

- `reverse.py`
- `postgis.py`
- 선택 의존성 `python-vworld-api`

흐름:

```text
Juso 내비게이션용DB 건물정보 TXT
  -> iter_navigation_building_records()
  -> NavigationBuildingRecord
  -> RoadAddressPointStore
  -> road_address_points 테이블

ReverseGeocoder.reverse_road_address()
  -> 오프라인 최근접 주소점 조회
  -> 실패하면 VWorldReverseGeocoder로 보조 호출
```

이 기능은 "좌표가 들어왔을 때 표시할 도로명주소"를 찾는 데 적합합니다. 법적
필지 판정은 PNU가 있는 지적 폴리곤을 별도로 적재한 뒤 `ST_Contains` 또는
`ST_Covers`로 구현해야 합니다.

## 테이블을 코드와 연결해서 보기

### `road_name_addresses`

코드:

- `store.py`
- `ROAD_TABLE`
- `ROAD_NAME_ADDRESS_COLUMNS`
- `ROAD_DERIVED_COLUMNS`

역할:

- Juso "도로명주소 한글" 마스터 행 저장
- 도로명주소 관리번호, 법정동코드, 도로명코드, 건물번호 보관
- PNU와 코드 조각 파생

처음 볼 컬럼:

- `road_address_management_number`
- `legal_dong_code`
- `road_name_code`
- `building_main_no`
- `building_sub_no`
- `building_management_number`
- `pnu`

### `related_jibuns`

코드:

- `store.py`
- `JIBUN_TABLE`
- `RELATED_JIBUN_COLUMNS`

역할:

- 도로명주소와 연결된 지번/PNU 보관
- 한 도로명주소가 여러 지번과 연결되는 상황 처리

### `legal_dong_codes`

코드:

- `legal_dong.py`
- `postgis.py`
- `LEGAL_DONG_TABLE`

역할:

- 법정동코드 마스터
- 활성/폐지 상태 보관
- 시도/시군구/읍면동/리 파생 컬럼 제공

### `legal_dong_code_aliases`

코드:

- `postgis.py`
- `DEFAULT_LEGAL_DONG_ALIASES`
- `resolve_legal_dong_code`

역할:

- 외부 GIS 소스 코드와 CSV 마스터 코드 차이 처리
- CSV 마스터를 오염시키지 않고 FK 무결성 유지

### `legal_dong_boundaries`

코드:

- `postgis.py`
- `load_boundary_zips`
- `read_boundary_zip`

역할:

- 시도/시군구/읍면동 경계 폴리곤 저장
- 행정구역 리버스 지오코딩 기반 제공

### `road_address_points`

코드:

- `reverse.py`
- `RoadAddressPointStore`
- `NavigationBuildingRecord`

역할:

- Juso 내비게이션용DB 건물 좌표 저장
- 좌표에서 가장 가까운 도로명주소 찾기

## 기능별로 어디를 고치면 되는가

| 하고 싶은 일 | 먼저 볼 파일 | 같이 볼 파일 |
| --- | --- | --- |
| Juso 검색 API 파라미터 추가 | `client.py` | `models.py`, `_http.py` |
| API 응답 모델 필드 추가 | `models.py` | `client.py`, 테스트 |
| 도로명주소 TXT 컬럼 변경 대응 | `data.py` | `models.py`, `store.py` |
| SQLite 저장소 인덱스 추가 | `store.py` | `docs/address-db-schema.md` |
| 법정동 CSV 컬럼 alias 추가 | `legal_dong.py` | `models.py` |
| 법정동 경계 매핑 수정 | `postgis.py` | `docs/legal-dong-postgis-report.md` |
| 주소점 리버스 지오코딩 개선 | `reverse.py` | `docs/reverse-geocoding.md` |
| 외부 API 보조 호출 변경 | `reverse.py` | `python-vworld-api` |

## 테스트를 읽는 순서

테스트는 기능별 입문 자료로도 쓸 수 있습니다.

```text
tests/test_client.py       Juso API 응답 파싱
tests/test_data.py         TXT/ZIP 파서
tests/test_store.py        SQLite 적재와 일변동 반영
tests/test_legal_dong.py   법정동 CSV/API 행 정규화
tests/test_postgis.py      PostGIS 메타데이터와 별칭 매핑
tests/test_reverse.py      주소점 파서와 리버스 지오코딩
```

처음에는 테스트의 fixture 데이터를 보고, 그 데이터가 어떤 모델과 테이블로 가는지
따라가면 코드 이해가 훨씬 빠릅니다.

## 로컬 검증 명령

기본 검증:

```powershell
python -m ruff check .
python -m pytest
python -m mypy src/kraddr/geo
```

PostGIS 기능까지 확인하려면 WSL2에서 `python-kraddr-geo[postgis]`를 설치하고 Docker
PostGIS를 띄운 뒤 샘플 적재를 실행합니다. 전체 재적재 예시는
[legal-dong-postgis-report.md](legal-dong-postgis-report.md)에 있습니다.

## 새 기능을 추가할 때 지켜야 할 원칙

1. 공급자 원본 컬럼은 문자열로 유지합니다. 코드 앞의 0이 의미를 갖습니다.
2. CSV 법정동코드 마스터에 없는 코드를 임의로 넣지 않습니다.
3. 외부 소스 코드가 다르면 별칭 테이블로 해결합니다.
4. 대량 데이터는 Python 반복 필터링보다 DB 인덱스와 SQL 조건으로 처리합니다.
5. 좌표 데이터는 기준 좌표계를 명시합니다. 현재 PostGIS 공간 데이터는 주로
   EPSG:5179를 기준으로 둡니다.
6. 온라인 API는 오프라인 DB 실패 시 보조 경로로 쓰는 것이 기본 설계입니다.
7. 문서와 docstring은 한글로 작성합니다. 기술 식별자는 원문을 유지합니다.
8. 불필요한 래퍼를 만들지 않습니다. 외부 라이브러리의 공개 API가 요구사항과
   맞으면 얇은 전달 계층 대신 그 API를 직접 사용하고, 예외 변환이나 경계 책임이
   분명할 때만 래퍼를 둡니다.
9. 다른 라이브러리에서 이미 검증된 구현이 있으면 "최소 수정"보다 그 구현을
   kraddr.geo 코드에 직접 반영하는 쪽을 우선합니다. 단순 위임으로 숨기지 말고,
   출처와 라이선스를 확인한 뒤 필요한 로직과 테스트 관점을 가져와 적용합니다.

## 용어 빠른 참조

| 용어 | 의미 | 코드에서 보는 곳 |
| --- | --- | --- |
| 법정동코드 | 10자리 지역 기준 코드 | `LegalDongRecord` |
| PNU | 19자리 필지 식별자 | `store._pnu` |
| 도로명주소 관리번호 | 26자리 건물/주소 식별자 | `road_address_management_number` |
| 도로명코드 | 12자리 도로 식별자 | `road_name_code` |
| 관련 지번 | 도로명주소에 연결된 지번 행 | `RelatedJibunRecord` |
| 경계 폴리곤 | 행정구역 공간 경계 | `legal_dong_boundaries` |
| 주소점 | 건물 중심 또는 출입구 좌표 | `road_address_points` |
| 별칭 | 소스 코드와 마스터 코드 차이 보정 | `legal_dong_code_aliases` |

## 다음에 더 보강하면 좋은 문서

- 필지 폴리곤/PNU 적재 문서
- 도로 중심선과 건물 footprint 적재 문서
- 검색 랭킹과 한글 주소 정규화 문서
- 운영 환경에서 전체분 + 일변동을 자동 재생하는 배치 문서
