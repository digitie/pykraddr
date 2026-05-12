# 리버스 지오코딩 설계

작성일: 2026-05-09

이 문서는 kraddr.geo가 좌표에서 도로명주소를 얻는 방식을 설명합니다. 이후 Codex
세션에서 리버스 지오코딩 동작을 바꾸기 전에 먼저 읽어야 할 기준 문서입니다.

## 결론

오프라인 원천은 존재합니다.

Juso "제공하는 주소" 페이지에는 좌표를 포함한 TXT 자료가 있습니다.

- `위치정보요약DB (.txt)`: 위치 기반 서비스용 도로명주소와 좌표 요약 DB
- `내비게이션용DB (.txt)`: 건물 중심, 주출입구, 보조출입구 좌표를 포함한
  건물 단위 도로명주소 자료
- `도로명주소 출입구 정보 (.txt)`: 도로명주소 출입구 좌표

같은 페이지의 스키마 설명에 따르면 내비게이션용DB 건물정보 테이블은 다음
값들을 포함합니다.

- 도로명코드
- 지하여부
- 건물 본번/부번
- 우편번호
- 건물 관리번호
- 건물 중심 x/y
- 출입구 x/y
- 변동 사유 코드 `31`, `34`, `63`

공식 자료:

- [Juso 제공하는 주소](https://business.juso.go.kr/addrlink/elctrnMapProvd/geoDBDwldList.do?menu=%EA%B5%AC%EC%97%AD%EC%9D%98+%EB%8F%84%ED%98%95)

## 구현 전략

kraddr.geo는 오프라인 우선 방식을 사용합니다.

1. Juso 내비게이션용DB 건물정보 TXT를 PostGIS `road_address_points`에 적재합니다.
2. WGS84 lon/lat 좌표를 받아 `road_address_points.geom`에서 최근접 주소점을
   찾습니다.
3. 오프라인 테이블이 설정되지 않았거나, 설정한 거리 안에 주소점이 없으면
   `python-vworld-api`를 통해 VWorld를 호출합니다.

VWorld 보조 호출은 `vworld.VworldClient.reverse_geocode_latlon()`을 사용하며,
내부적으로 VWorld Geocoder API 2.0 `getaddress`를 호출합니다.

참고:

- [VWorld API 참조](https://www.vworld.kr/dev/v4apiRefer.do)
- [python-vworld-api 저장소](https://github.com/digitie/python-vworld-api)

## Python API

### 오프라인 주소점

```python
from kraddr.geo import RoadAddressPointStore

url = "postgresql+psycopg://postgres:postgres@localhost:55433/kraddr_geo"

with RoadAddressPointStore(url, schema="kraddr") as store:
    result = store.load_navigation_building_archive(
        "/mnt/f/data/juso/navigation/NAVIBUILDING.zip",
        replace=True,
    )
    print(result)

    address = store.nearest_road_address(lon=127.1013, lat=37.4023)
    print(address.road_address if address else None)
```

`RoadAddressPointStore`는 권위 주소점을 EPSG:5179로 저장합니다. Juso
내비게이션용DB 좌표가 GRS80 UTM-K 기준이기 때문입니다. 편의 메서드
`nearest_road_address(lon=..., lat=...)`는 EPSG:4326을 입력받고, PostGIS 내부에서
질의 좌표를 변환합니다.

### VWorld 보조 호출

python-vworld-api가 패키지 인덱스에 배포되기 전까지는 로컬 형제 저장소 또는 GitHub에서
설치합니다.

```bash
python -m pip install "git+https://github.com/digitie/python-vworld-api.git"
```

사용 예시:

```python
from kraddr.geo import VWorldReverseGeocoder

geocoder = VWorldReverseGeocoder.from_env()
result = geocoder.reverse_road_address(lon=127.1013, lat=37.4023)
print(result.road_address if result else None)
```

python-vworld-api가 읽는 환경 변수:

```bash
VWORLD_API_KEY="발급받은 키"
VWORLD_DOMAIN="필요한 경우 등록 도메인"
```

### 오프라인 우선 래퍼

```python
from kraddr.geo import ReverseGeocoder, RoadAddressPointStore, VWorldReverseGeocoder

with RoadAddressPointStore(url, schema="kraddr") as store:
    geocoder = ReverseGeocoder(
        offline_store=store,
        vworld=VWorldReverseGeocoder.from_env(),
        max_offline_distance_m=50,
    )
    result = geocoder.reverse_road_address(lon=127.1013, lat=37.4023)
```

## PostGIS 테이블

`road_address_points`:

```text
building_management_number PK
legal_dong_code
sido_name
sigungu_name
eup_myeon_dong_name
road_name_code
road_name
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
source
loaded_at
geom geometry(Point, 5179)
```

인덱스:

```text
building_management_number PK
ix_road_address_points_legal_dong
ix_road_address_points_road_lookup
ix_road_address_points_source
geom GiST index
```

`coordinate_source` 값:

- `entrance`: 주출입구 x/y가 있습니다.
- `center`: 주출입구가 없어 건물 중심 x/y를 사용했습니다.

## TXT 적재 규칙

`iter_navigation_building_records()`는 TXT 또는 ZIP 바이트를 읽습니다. Juso
내비게이션용DB 건물정보 레이아웃을 기준으로 하며, 건물정보 스키마보다 필드가
짧은 다른 멤버는 건너뜁니다.

전체 적재:

```python
store.load_navigation_building_archive(path, replace=True)
```

일변동 반영:

```python
records = iter_navigation_building_records(path)
store.apply_navigation_building_changes(records)
```

변동 코드 동작:

| 코드 | 의미 | 동작 |
| --- | --- | --- |
| `31` | 신규 | 삽입 또는 갱신 |
| `34` | 변경 | 삽입 또는 갱신 |
| `63` | 삭제 | 건물 관리번호로 삭제 |

## 질의 의미

오프라인 리버스 지오코딩은 최근접 주소점 조회입니다. "이 핀에 표시할
도로명주소가 무엇인가?"에 적합하지만, 법적 필지 판정에는 적합하지 않습니다.

도심에서는 `max_offline_distance_m`을 30-50m 정도로 보수적으로 두는 것이
좋습니다. 값을 너무 크게 잡으면 하천, 큰 도로, 넓은 필지를 건너 의외의 주소가
매칭될 수 있습니다.

필지 단위 리버스 지오코딩은 PNU 키를 가진 지적 폴리곤을 적재한 뒤
`ST_Contains` 또는 `ST_Covers`로 별도 처리해야 합니다.

## 검증 상태

테스트로 확인한 항목:

- 내비게이션용DB 건물정보 TXT/ZIP 파싱
- 출입구 좌표가 없을 때 건물 중심 좌표로 대체
- `road_address_points` PostGIS 메타데이터
- 모의 vworld 클라이언트를 통한 VWorld 응답 파싱
- 오프라인 우선 보조 호출 동작
- WSL2 Docker PostGIS에서 테이블 생성, 1건 적재, 최근접 주소 조회

실제 VWorld 호출은 `VWORLD_API_KEY`가 필요합니다. 구현 당시 로컬 환경에 키가
없었으므로 네트워크 호출은 모의 테스트로 검증했습니다.
