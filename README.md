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
also pass an existing SQLAlchemy `Engine`.

The TXT parser also works directly:

```python
from pykraddr import iter_road_name_address_records

for record in iter_road_name_address_records(zip_path):
    print(record.road_address_management_number, record.road_name)
    break
```
