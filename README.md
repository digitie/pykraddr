# pykraddr

`pykraddr` is an unofficial Python helper for Korea Juso road-name address APIs
and the downloadable "도로명주소 한글" TXT datasets from `business.juso.go.kr`.

Popup APIs are intentionally not wrapped. The library focuses on server-style
search APIs and dataset loading.

## Search APIs

```python
from pykraddr import KrAddrClient

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

Implemented endpoints:

- `addrLinkApi.do`: 도로명주소 검색
- `addrEngApi.do`: 영문주소 검색
- `addrCoordApi.do`: 좌표제공 검색
- `addrDetailApi.do`: 상세주소 검색
- map API guide/source ZIP download helper

## Road-Name Address Korean Data

```python
from pykraddr import RoadNameAddressDataClient, RoadNameAddressStore

data = RoadNameAddressDataClient()
zip_path = data.download_latest_full("data/juso")

with RoadNameAddressStore("data/juso/rnaddrkor.sqlite") as store:
    store.load_full_archive(zip_path, replace=True)
    print(store.count_road_addresses())
```

Daily change updates use the Juso movement reason code:

- `31`: insert
- `34`: update
- `63`: delete

```python
from datetime import date

paths = data.download_daily_changes(
    "data/juso/daily",
    start=date(2026, 4, 1),
    end=date(2026, 4, 30),
)

with RoadNameAddressStore("data/juso/rnaddrkor.sqlite") as store:
    for path in paths:
        store.apply_daily_archive(path)
```

`RoadNameAddressStore` uses SQLAlchemy 2 Core with SQLite by default. You can
also pass an existing SQLAlchemy `Engine`. The store keeps the official TXT
columns and adds indexed derived keys such as `sigungu_code`, `road_number`,
`building_management_number`, and `pnu`.

Useful lookup helpers:

```python
rows = store.get_road_addresses_by_management_number("1111010100100010000000001")
parcel_rows = store.find_road_addresses_by_pnu("1111010100000010000")
```

See [docs/address-db-schema.md](docs/address-db-schema.md) for the optimized
SQLAlchemy schema, identifier structure, ETL flow, and future maintenance notes.

## Legal-Dong Codes and PostGIS Boundaries

PostGIS/GIS loading is available as an optional extra:

```bash
python -m pip install "pykraddr[postgis]"
```

```python
from pathlib import Path
from pykraddr.postgis import PostGISLegalDongStore

url = "postgresql+psycopg://postgres:postgres@localhost:55433/pykraddr"

with PostGISLegalDongStore(url, schema="kraddr") as store:
    store.create_schema()
    store.load_legal_dong_csv(Path("dataset/국토교통부_법정동코드_20250805.csv"))
    result = store.load_boundary_zips(sorted(Path("dataset").glob("N3A_*.zip")))
    print(result)
```

The PostGIS loader uses `psycopg` COPY for legal-dong CSV rows and GeoPandas /
GeoAlchemy2 for SHP ZIP boundary loading. CSV legal-dong codes remain the
master; source-specific GIS differences, such as VWorld/N3A Sejong
`3600000000` mapping to code.go.kr `3611000000`, are handled through aliases.
The WSL2 validation report is in
[docs/legal-dong-postgis-report.md](docs/legal-dong-postgis-report.md). See
[docs/geocoding-readiness.md](docs/geocoding-readiness.md) for the remaining
datasets needed for precise geocoding and reverse geocoding.

The TXT parser also works directly:

```python
from pykraddr import iter_road_name_address_records

for record in iter_road_name_address_records(zip_path):
    print(record.road_address_management_number, record.road_name)
    break
```
