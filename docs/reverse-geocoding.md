# Reverse Geocoding Design

Date: 2026-05-09

This note documents how pykraddr resolves a coordinate to a road-name address.
It is meant to be the first place future Codex sessions read before changing
reverse-geocoding behavior.

## Finding

An offline source does exist.

The Juso "provided address" page lists coordinate-bearing datasets:

- `위치정보요약DB (.txt)`: road-name address and coordinate summary DB for
  location-based services.
- `내비게이션용DB (.txt)`: building-level road-name address data with building
  center, main entrance, and auxiliary entrance coordinates.
- `도로명주소 출입구 정보 (.txt)`: road-name address entrance coordinates.

The same page documents that the navigation DB building table includes:

- road-name code
- underground flag
- building main/sub number
- postal code
- building management number
- building center x/y
- entrance x/y
- movement reason code `31`, `34`, `63`

Source:

- [Juso provided address data](https://business.juso.go.kr/addrlink/elctrnMapProvd/geoDBDwldList.do?menu=%EA%B5%AC%EC%97%AD%EC%9D%98+%EB%8F%84%ED%98%95)

## Implemented Strategy

pykraddr now uses an offline-first design:

1. Load Juso navigation DB building TXT rows into PostGIS
   `road_address_points`.
2. Reverse geocode a WGS84 lon/lat point by nearest-neighbor search against
   `road_address_points.geom`.
3. If the offline table is not configured or no row is within the configured
   distance, call VWorld through `pyvworld`.

The VWorld fallback uses pyvworld's `VworldClient.reverse_geocode_latlon()`,
which calls VWorld Geocoder API 2.0 `getaddress`.

Source:

- [VWorld API reference](https://www.vworld.kr/dev/v4apiRefer.do)
- [pyvworld repository](https://github.com/digitie/pyvworld)

## Python API

### Offline Address Points

```python
from pykraddr import RoadAddressPointStore

url = "postgresql+psycopg://postgres:postgres@localhost:55433/pykraddr"

with RoadAddressPointStore(url, schema="kraddr") as store:
    result = store.load_navigation_building_archive(
        "/mnt/f/data/juso/navigation/NAVIBUILDING.zip",
        replace=True,
    )
    print(result)

    address = store.nearest_road_address(lon=127.1013, lat=37.4023)
    print(address.road_address if address else None)
```

`RoadAddressPointStore` stores authoritative points in EPSG:5179 because Juso
documents the navigation DB coordinates as GRS80 UTM-K. The convenience method
`nearest_road_address(lon=..., lat=...)` accepts EPSG:4326 and transforms the
query point inside PostGIS.

### VWorld Fallback

Install pyvworld from the local sibling repo or GitHub until it is published to
the package index:

```bash
python -m pip install "git+https://github.com/digitie/pyvworld.git"
```

Then:

```python
from pykraddr import VWorldReverseGeocoder

geocoder = VWorldReverseGeocoder.from_env()
result = geocoder.reverse_road_address(lon=127.1013, lat=37.4023)
print(result.road_address if result else None)
```

Required environment variables are handled by pyvworld:

```bash
VWORLD_API_KEY="issued-key"
VWORLD_DOMAIN="registered-domain-if-needed"
```

### Offline-First Wrapper

```python
from pykraddr import ReverseGeocoder, RoadAddressPointStore, VWorldReverseGeocoder

with RoadAddressPointStore(url, schema="kraddr") as store:
    geocoder = ReverseGeocoder(
        offline_store=store,
        vworld=VWorldReverseGeocoder.from_env(),
        max_offline_distance_m=50,
    )
    result = geocoder.reverse_road_address(lon=127.1013, lat=37.4023)
```

## PostGIS Table

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

Indexes:

```text
building_management_number PK
ix_road_address_points_legal_dong
ix_road_address_points_road_lookup
ix_road_address_points_source
GiST index on geom
```

`coordinate_source` is:

- `entrance`: primary entrance x/y was present.
- `center`: entrance was missing and building center x/y was used.

## TXT Loading Rules

`iter_navigation_building_records()` reads TXT or ZIP bytes. It uses the Juso
navigation DB building layout and skips non-building members whose line length
is shorter than the building-info schema.

Full load:

```python
store.load_navigation_building_archive(path, replace=True)
```

Daily changes:

```python
records = iter_navigation_building_records(path)
store.apply_navigation_building_changes(records)
```

Movement-code behavior:

| Code | Meaning | Behavior |
| --- | --- | --- |
| `31` | new | upsert |
| `34` | changed | upsert |
| `63` | deleted | delete by building management number |

## Query Semantics

Offline reverse geocoding is a nearest-address-point lookup, not a parcel
containment operation. This is appropriate for "which road-name address should
be shown for this pin?" but not for cadastral legal analysis.

Use a conservative `max_offline_distance_m`, usually 30-50m in dense urban
areas. Larger values may produce surprising matches across rivers, roads, or
large parcels.

For parcel-level reverse geocoding, add cadastral polygon data keyed by PNU and
query with `ST_Contains` or `ST_Covers`. That is intentionally separate from
road-name address-point lookup.

## Validation Status

Implemented tests cover:

- navigation DB building TXT/ZIP parsing
- entrance-to-center coordinate fallback
- PostGIS metadata for `road_address_points`
- VWorld response parsing through a fake pyvworld client
- offline-first fallback behavior
- WSL2 Docker PostGIS smoke test for table creation, one-row load, and nearest
  address lookup

Live VWorld calls require `VWORLD_API_KEY`; no key was present in the local
environment during this implementation, so network calls are intentionally
covered by mock tests.
