# 법정동/PostGIS 적재 검증 보고서

작성일: 2026-05-09

검증 환경:

- WSL2 Ubuntu
- Python 3.12
- Docker PostGIS
- PostgreSQL/PostGIS 스키마: `kraddr`

## 원천 자료

법정동코드 CSV:

- 로컬 파일: `/mnt/f/dev/tripmate/dataset/국토교통부_법정동코드_20250805.csv`
- 인코딩: CP949
- 확인된 컬럼: `법정동코드`, `법정동명`, `폐지여부`
- 적재 행 수: `49,861`
- 활성 행 수: `20,555`
- 폐지 행 수: `29,306`

경계 SHP ZIP:

- 디렉터리: `/mnt/f/dev/tripmate/dataset`
- 파일:
  - `N3A_G0010000.zip`
  - `N3A_G0100000.zip`
  - `N3A_G0110000.zip`
- 소스 좌표계: Korea 2000 통합 좌표계, EPSG:5179 호환
- 목표 지오메트리: PostGIS `MULTIPOLYGON`, SRID `5179`

공공데이터 참고:

- data.go.kr 데이터셋: `국토교통부_전국 법정동_20250807`
- 제공 기관: 국토교통부
- 갱신 주기: 연간
- data.go.kr에 표시된 다음 등록 예정일: `2026-08-31`
- 포털 설명상 이 자료는 토지 행정 시스템에서 쓰는 법정지역이며 행정표준코드
  관리 시스템 자료를 기준으로 합니다.

## 구현 스키마

### `legal_dong_codes`

CSV가 마스터입니다. 이 테이블은 CSV/code.go.kr 원천에 없는 법정동코드를 임의로
만들지 않습니다.

기본키:

```text
legal_dong_code
```

주요 파생 컬럼:

```text
sido_code
sigungu_code
eup_myeon_dong_code
ri_code
legal_dong_level
is_active
```

코드 구조:

```text
legal_dong_code(10) = sido(2) + sigungu(3) + eup/myeon/dong(3) + ri(2)
```

### `legal_dong_code_aliases`

경계 자료나 외부 소스의 코드가 CSV 마스터와 다를 때 쓰는 별칭 테이블입니다.

기본키:

```text
source_system
source_layer
source_code
```

FK:

```text
legal_dong_code_aliases.legal_dong_code
  -> legal_dong_codes.legal_dong_code
```

검증 중 적재한 기본 별칭:

| source_system | source_layer | source_code | legal_dong_code | 사유 |
| --- | --- | --- | --- | --- |
| `vworld_n3a` | `sido` | `3600000000` | `3611000000` | VWorld/N3A 시도 경계 코드가 code.go.kr 법정동 마스터와 다름 |

이 방식은 `3600000000`을 CSV 마스터에 넣지 않으면서도, SHP 소스 행을 공식
`3611000000` 법정동코드에 연결합니다.

### `legal_dong_boundaries`

기본키:

```text
id
```

FK:

```text
legal_dong_boundaries.legal_dong_code
  -> legal_dong_codes.legal_dong_code
```

원본 SHP 코드는 항상 `source_code`에 보존합니다. `legal_dong_code`는 정확 매칭
또는 별칭 해석 이후의 CSV 마스터 코드입니다.

주요 컬럼:

```text
legal_dong_code
boundary_level
source_layer
source_file
source_code
source_name
mapping_status
geom
```

매핑 상태:

- `matched`: 소스 코드가 CSV 마스터에 있고 활성 상태입니다.
- `alias_mapped`: `legal_dong_code_aliases`를 통해 매핑했습니다.
- `inactive_legal_dong_code`: 소스 코드가 CSV 마스터에 있으나 폐지 상태입니다.
- `alias_target_inactive`: 별칭 대상 코드가 폐지 상태입니다.
- `missing_legal_dong_code`: 정확 매칭 또는 별칭 대상이 없습니다.

검증된 제약/인덱스:

```text
fk_alias_legal_dong_code
fk_boundary_legal_dong_code
legal_dong_boundaries_pkey
legal_dong_code_aliases_pkey
uq_boundary_source_layer_code
idx_legal_dong_boundaries_geom
ix_legal_dong_boundaries_legal_code
ix_legal_dong_boundaries_source_code
ix_legal_dong_boundaries_mapping_status
```

### `legal_dong_boundary_mapping_issues`

다음 행을 검토용으로 반환하는 뷰입니다.

- `legal_dong_code IS NULL`
- 매핑된 코드가 폐지 상태
- `mapping_status NOT IN ('matched', 'alias_mapped')`

별칭으로 해결된 행은 정상 매핑으로 보며 이 뷰에 나타나지 않습니다.

## WSL2 전체 재적재 명령

```bash
cd /mnt/f/dev/pykraddr
python3 -m venv ~/.cache/pykraddr-venv
source ~/.cache/pykraddr-venv/bin/activate
python -m pip install -e ".[dev,postgis]"

docker run -d --name pykraddr-postgis \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=pykraddr \
  -p 55433:5432 \
  postgis/postgis:16-3.4
```

```python
from pathlib import Path
from pykraddr.postgis import PostGISLegalDongStore

url = "postgresql+psycopg://postgres:postgres@localhost:55433/pykraddr"
csv_path = Path("/mnt/f/dev/tripmate/dataset/국토교통부_법정동코드_20250805.csv")
zip_paths = sorted(Path("/mnt/f/dev/tripmate/dataset").glob("N3A_*.zip"))

with PostGISLegalDongStore(url, schema="kraddr") as store:
    store.reset(recreate=True)
    store.load_legal_dong_csv(csv_path, replace=True)
    result = store.load_boundary_zips(zip_paths, replace=True, batch_size=10_000)
    print(result)
    print(store.boundary_mapping_issues(limit=20))
```

적재 속도를 높이려면 `/mnt/f/...`의 ZIP을 WSL2 ext4 파일 시스템으로 복사한 뒤 그
경로에서 읽는 것이 좋습니다.

## 전체 재적재 검증 결과

검증 흐름:

1. Docker PostGIS 컨테이너를 새로 시작했습니다.
2. `kraddr` 스키마를 삭제하고 다시 만들었습니다.
3. CSV 마스터를 적재했습니다.
4. 기본 법정동 별칭을 적재했습니다.
5. 모든 `N3A_*.zip` SHP 파일을 적재했습니다.
6. FK, 별칭, 매핑 상태, 이슈 뷰를 조회했습니다.

적재 건수:

```text
legal_dong_codes: 49,861
active legal_dong_codes: 20,555
inactive legal_dong_codes: 29,306
legal_dong_code_aliases: 1
legal_dong_boundaries: 5,288
FK 매핑 경계: 5,288
누락 법정동코드 경계: 0
정확 매칭 경계: 5,285
별칭 매핑 경계: 1
폐지 법정동코드 경계: 2
```

경계 상태별 건수:

```text
eup_myeon_dong / matched: 5,005
eup_myeon_dong / inactive_legal_dong_code: 2
sido / matched: 16
sido / alias_mapped: 1
sigungu / matched: 264
```

세종특별자치시 별칭 검증:

```text
source_code=3600000000
legal_dong_code=3611000000
mapping_status=alias_mapped
```

## 남은 검토 사항

| 소스 파일 | 레이어 | 소스 코드 | 소스 이름 | 결과 |
| --- | --- | --- | --- | --- |
| `N3A_G0110000.zip` | `eup_myeon_dong` | `2671031000` | 일광면 | CSV에는 있으나 폐지 상태 |
| `N3A_G0110000.zip` | `eup_myeon_dong` | `4784035000` | 금수면 | CSV에는 있으나 폐지 상태 |

두 행은 CSV 마스터에 존재하므로 FK 무결성은 만족합니다. 다만 활성 행만 필요한
애플리케이션 쿼리에서는 제외해야 합니다.

활성 경계 조회 예시:

```sql
SELECT b.*
FROM kraddr.legal_dong_boundaries AS b
JOIN kraddr.legal_dong_codes AS c
  ON b.legal_dong_code = c.legal_dong_code
WHERE c.is_active IS TRUE
  AND b.mapping_status IN ('matched', 'alias_mapped');
```

## 권장 사항

CSV 마스터 + 별칭 테이블 설계를 유지합니다.

- code.go.kr/data.go.kr CSV를 법정동코드의 유일한 기준으로 유지합니다.
- 소스별 GIS 코드 차이는 `source_code`에 드러나게 둡니다.
- 해결 가능한 모든 경계 행은 유효한 FK를 갖게 합니다.
- 해결되지 않거나 폐지된 행은 `mapping_status`와 이슈 뷰로 검토할 수 있게 둡니다.
