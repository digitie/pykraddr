# 지오코딩 및 리버스 지오코딩 준비 상태

작성일: 2026-05-09

이 문서는 현재 pykraddr 로더로 구축할 수 있는 DB가 지오코딩과 리버스
지오코딩에 어느 정도 충분한지 평가합니다.

## 현재 포함된 구성

현재 로더가 만들 수 있는 기반 데이터:

- `RoadNameAddressStore`가 적재하는 Juso "도로명주소 한글" TXT 마스터
- `RoadNameAddressStore`가 적재하는 관련 지번 TXT
- `PostGISLegalDongStore`가 적재하는 data.go.kr/code.go.kr 법정동 CSV
- GeoPandas/PostGIS로 적재하는 VWorld/N3A 법정동 경계 SHP ZIP
- 법정동코드 소스 차이를 다루는 `legal_dong_code_aliases`
- Juso 내비게이션용DB 건물정보 TXT를 적재하는 `road_address_points`
- `pyvworld`를 통한 VWorld 리버스 지오코딩 보조 호출

## 가능한 일

### 행정구역 리버스 조회

좌표가 주어졌을 때 시도/시군구/읍면동 경계 안에 들어가는지 찾을 수 있습니다.
경계 행은 `legal_dong_codes`와 조인할 수 있습니다.

운영 쿼리에서는 보통 다음 조건을 함께 둡니다.

```sql
b.mapping_status IN ('matched', 'alias_mapped')
AND c.is_active IS TRUE
```

### 주소 키 정규화

"도로명주소 한글" TXT는 다음 식별자 기반 조회와 조인에 유용합니다.

- 법정동코드
- 도로명코드
- 건물 본번/부번
- 우편번호
- PNU
- 도로명주소/건물 관리번호

관련 지번 행은 관리번호를 통해 도로명주소 마스터 행과 연결됩니다.

### 도로명주소 리버스 조회

Juso 내비게이션용DB 건물정보 TXT를 `road_address_points`에 적재하면 WGS84 좌표에서
가장 가까운 도로명주소점을 찾을 수 있습니다.

오프라인 주소점 저장소가 없거나 설정한 거리 안에 결과가 없으면
`VWorldReverseGeocoder`가 `pyvworld`를 통해 VWorld Geocoder API 2.0을 호출할 수
있습니다.

## 아직 부족한 부분

현재 DB는 모든 수준의 지오코딩/리버스 지오코딩을 완성하지는 않습니다.

### 정방향 지오코딩

정방향 지오코딩은 텍스트 주소를 좌표로 바꾸는 작업입니다.

"도로명주소 한글" TXT 마스터만으로는 주소 행을 식별할 수 있지만, 각 건물이나
주소의 좌표를 직접 반환할 수 없습니다. Juso 내비게이션용DB나 위치정보요약DB
좌표를 함께 적재해야 정밀 좌표 반환이 가능합니다.

필요한 추가 요소:

- `building_management_number` 또는 `road_address_management_number` 기준 주소점
- 좌표 출처와 좌표 유형
- `geom geometry(Point, 5179)`
- API/웹지도용 WGS84 변환 뷰 또는 lon/lat 생성 컬럼
- 좌표 품질 메타데이터: 출처, 관측일, 출입구/중심점/보간 여부

권장 테이블:

```text
address_points
  building_management_number PK
  road_address_management_number
  legal_dong_code
  pnu
  coordinate_source
  coordinate_type
  geom geometry(Point, 5179)
  lon
  lat
  loaded_at
```

현재 구현된 `road_address_points`는 이 권장안의 첫 단계입니다.

### 필지 단위 리버스 지오코딩

리버스 지오코딩은 여러 수준으로 나뉩니다.

1. 좌표가 속한 행정구역
2. 좌표가 속한 필지/지번
3. 가장 가까운 건물 또는 도로명주소

현재 DB는 1번을 지원합니다. `road_address_points`를 적재하면 3번의 최근접
도로명주소도 지원합니다. 하지만 2번의 필지 포함 관계는 지적 폴리곤이 있어야
합니다.

추가로 필요한 데이터:

- PNU 키를 가진 필지/지적 폴리곤
- 건물 관리번호를 가진 건물 외곽 폴리곤 또는 건축물 공간 데이터
- 도로명코드가 있는 도로 중심선

권장 테이블:

```text
parcel_boundaries
  pnu PK
  legal_dong_code
  mountain_yn
  lot_main_no
  lot_sub_no
  geom geometry(MultiPolygon, 5179)

building_footprints
  building_management_number PK
  legal_dong_code
  pnu
  geom geometry(MultiPolygon, 5179)

road_centerlines
  road_name_code
  road_name
  sigungu_code
  geom geometry(MultiLineString, 5179)
```

## 검색과 랭킹

실용적인 지오코더에는 테이블뿐 아니라 텍스트 검색과 랭킹도 필요합니다.

권장 추가 요소:

- 정규화된 한국 주소 토큰 테이블
- 도로명주소/지번 주소 검색용 구체화 뷰
- 오타 허용 검색용 PostgreSQL `pg_trgm` 확장
- 한국 주소 구성요소별 토큰 인덱스
- 건물명, 아파트명, 별칭 정규화
- 이전 주소와 변동 이력 처리

후보 뷰:

```text
geocode_road_address_search
geocode_jibun_address_search
reverse_geocode_admin_area
reverse_geocode_parcel
reverse_geocode_nearest_address_point
```

오프라인 우선 도로명주소 리버스 지오코딩 설계와 VWorld 보조 호출은
[reverse-geocoding.md](reverse-geocoding.md)에 따로 정리했습니다.

## 좌표계

현재 SHP 경계와 주소점은 SRID `5179` 기준으로 저장합니다. API와 웹지도에서는
보통 WGS84가 필요하므로 질의나 뷰에서 `4326`으로 변환합니다.

권장 방식:

- 권위 좌표는 EPSG:5179로 저장합니다.
- API 응답용 EPSG:4326 변환 뷰를 추가합니다.
- 필요하면 투영 좌표와 lon/lat을 함께 반환합니다.

예시:

```sql
SELECT
  legal_dong_code,
  ST_AsGeoJSON(ST_Transform(geom, 4326)) AS geojson
FROM kraddr.legal_dong_boundaries;
```

## 품질 점검 항목

운영 지오코딩 인프라로 보기 전에 다음 점검을 반복 실행하는 것이 좋습니다.

- 활성 도로명주소가 좌표를 갖는지 확인합니다.
- 좌표가 활성 법정동코드와 조인되는지 확인합니다.
- 관련 지번 PNU가 필지 폴리곤과 매칭되는지 확인합니다.
- 경계와 필지 폴리곤이 `ST_IsValid(geom)`을 통과하는지 확인합니다.
- 읍면동은 시군구 안에, 시군구는 시도 안에 들어가는 위계 포함 관계를
  확인합니다.
- 별칭 매핑은 소스별로 검토하고 CSV 마스터 테이블에는 넣지 않습니다.
- 일변동 주소 델타가 고아 좌표 행을 만들지 않는지 확인합니다.

## 결론

현재 DB는 법정동 조회, 행정구역 리버스 지오코딩, 주소 키 정규화, 그리고 Juso
내비게이션용DB 주소점 적재 후 도로명주소 리버스 조회까지 지원할 수 있습니다.

정밀 정방향 지오코딩과 필지 단위 리버스 지오코딩까지 완성하려면 다음 작업이
남아 있습니다.

1. Juso 내비게이션용DB 또는 위치정보요약DB 주소점을 전국 단위로 적재합니다.
2. PNU 키를 가진 필지 폴리곤을 적재합니다.
3. 건물 관리번호를 가진 건물 외곽 폴리곤을 적재합니다.
4. 검색/랭킹 구체화 뷰와 텍스트 인덱스를 추가합니다.
