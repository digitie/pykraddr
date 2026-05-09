# Address DB Schema and Maintenance Notes

This document is the working schema note for future Codex sessions and library
maintenance. It reflects the Juso "도로명주소 한글" detail-page schema and the
user-provided PDF, `주소 코드 데이터 구조 및 API 정보.pdf`.

## Design Goals

- Keep every provider TXT column intact so a database row can be traced back to
  the original Juso record without lossy transforms.
- Add derived code columns for the identifiers that are expensive to compute on
  every query: legal-dong segments, road-code segments, and PNU.
- Use SQLAlchemy 2 Core tables and explicit indexes. SQLite is the default
  embedded store, but the schema is intentionally plain enough to port.
- Treat full monthly archives as the authoritative baseline and daily archives
  as movement-code deltas.
- Preserve identifier history by applying provider movement codes instead of
  inventing local surrogate keys.

## Core Korean Address Identifiers

### Legal Dong Code

`legal_dong_code` is the 10-digit legal-dong identifier used across Korean
land, cadastral, building, and address data.

| Segment | Meaning | Example |
| --- | --- | --- |
| 1-2 | Sido / city-province | `11` |
| 3-5 | Sigungu | `110` inside `11110` |
| 6-8 | Eup/myeon/dong | `101` inside `11110101` |
| 9-10 | Ri | `00` when not applicable |

The store materializes these derived columns:

- `sido_code`: first 2 digits
- `sigungu_code`: first 5 digits
- `eup_myeon_dong_code`: first 8 digits
- `ri_code`: last 2 digits

Use `sigungu_code` as the first regional filter for large offline lookups.

### PNU

`pnu` is the 19-digit parcel number used as the stable parcel join key.

```text
PNU = legal_dong_code(10) + mountain_yn(1) + lot_main_no(4) + lot_sub_no(4)
```

Rules implemented in `pykraddr.store`:

- `lot_main_no` and `lot_sub_no` are zero-padded to 4 digits.
- Empty lot numbers are stored as `0000`.
- `mountain_yn` defaults to `0` only when the source value is empty.

Example:

```text
legal_dong_code=1111010100, mountain_yn=0, lot_main_no=1, lot_sub_no=0
PNU=1111010100000010000
```

Use `pnu` to join road-name address rows to cadastral parcel datasets.

### Road-Name Address Management Number

`road_address_management_number` is the 26-digit road-name address/building
management number. The search API calls the same identifier `bdMgtSn`, so the
store also materializes `building_management_number` as an alias.

General structure:

| Segment | Meaning |
| --- | --- |
| 1-8 | Legal-dong upper code: sido + sigungu + eup/myeon/dong |
| 9-15 | Road number |
| 16 | Position code: ground, underground, aerial, water, etc. |
| 17-21 | Building main number, zero-padded |
| 22-26 | Building sub number, zero-padded |

The provider TXT schema marks a composite key, so pykraddr keeps that composite
primary key for safety:

```text
road_address_management_number
road_name_code
underground_yn
building_main_no
building_sub_no
```

In practice the 26-digit management number is the main absolute lookup key, and
it is indexed separately.

### Road Name Code

`road_name_code` is a 12-digit road identifier.

| Segment | Meaning |
| --- | --- |
| 1-5 | Sigungu code |
| 6-12 | Road number |

The store materializes:

- `road_sigungu_code`: first 5 digits
- `road_number`: last 7 digits

## Tables

### PostGIS Legal-Dong/GIS Schema

PostgreSQL/PostGIS support lives in `pykraddr.postgis` and is intended to be
run from WSL2 for local GIS work.

Install the GIS extra in WSL2:

```bash
cd /mnt/f/dev/pykraddr
python3 -m venv /tmp/pykraddr-venv
source /tmp/pykraddr-venv/bin/activate
python -m pip install -e ".[dev,postgis]"
```

The PostGIS schema adds:

- `legal_dong_codes`: data.go.kr/code.go.kr legal-dong code master table.
- `legal_dong_code_aliases`: source-specific aliases that point to CSV master
  codes without adding non-master codes to `legal_dong_codes`.
- `legal_dong_boundaries`: SHP boundary table with `geom MULTIPOLYGON(5179)`.
- `legal_dong_boundary_mapping_issues`: view for missing/inactive source codes.
- `road_address_points`: optional Juso navigation DB address-point table for
  offline road-name reverse geocoding.

The FK is:

```text
legal_dong_boundaries.legal_dong_code
  -> legal_dong_codes.legal_dong_code
```

CSV is the master. For example, VWorld/N3A uses `3600000000` for the Sejong
sido boundary, but code.go.kr/data.go.kr legal-dong master uses `3611000000`.
The loader resolves that through `legal_dong_code_aliases`:

```text
source_system=vworld_n3a
source_layer=sido
source_code=3600000000
legal_dong_code=3611000000
```

The source SHP code remains in `source_code`, and rows that cannot be mapped
are marked with `mapping_status`. Alias-mapped rows keep valid FK integrity
without polluting the CSV-master table.

Bulk-load choices:

- legal-dong CSV: `psycopg` COPY
- SHP ZIP: GeoPandas/pyogrio read path
- boundary write: `GeoDataFrame.to_postgis(..., chunksize=...)`
- geometry index: PostGIS GiST index created through GeoAlchemy2

See `docs/legal-dong-postgis-report.md` for the WSL2 command sequence and the
validated `tripmate` dataset mismatch report.

See `docs/geocoding-readiness.md` for what the current DB can and cannot do for
forward geocoding and reverse geocoding.

See `docs/reverse-geocoding.md` for coordinate-to-road-name-address lookup,
including Juso offline point storage and the `pyvworld` fallback.

### `road_address_points`

This optional PostGIS table stores Juso navigation DB building-info rows as
address points.

Primary key:

```text
building_management_number
```

Important columns:

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

`coordinate_source` is `entrance` when the provider row has entrance x/y, and
`center` when pykraddr falls back to the building center coordinate.

Nearest road-name reverse geocoding uses:

```sql
ORDER BY geom <-> ST_Transform(ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), 5179)
LIMIT 1
```

Keep this table separate from cadastral parcel polygons. It answers "nearest
road-name address point", not "which parcel contains this coordinate".

### `road_name_addresses`

This table stores the "도로명주소 한글" master rows.

Primary key:

```text
road_address_management_number
road_name_code
underground_yn
building_main_no
building_sub_no
```

Provider columns are loaded exactly as defined by the Juso TXT schema:

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

Derived columns:

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

Indexes:

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

The `ix_road_name_addresses_road_lookup` index covers this common API-shaped
lookup:

```text
road_name_code + underground_yn + building_main_no + building_sub_no
```

### `related_jibuns`

This table stores related jibun rows for road-name address records.

Primary key:

```text
road_address_management_number
legal_dong_code
mountain_yn
lot_main_no
lot_sub_no
```

Provider columns:

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
underground_yn
building_main_no
building_sub_no
change_reason_code
```

Derived columns:

```text
sido_code
sigungu_code
eup_myeon_dong_code
ri_code
road_sigungu_code
road_number
pnu
```

Indexes:

```text
ix_related_jibuns_road_mgmt
ix_related_jibuns_legal_dong
ix_related_jibuns_legal_lot
ix_related_jibuns_sigungu
ix_related_jibuns_pnu
```

Use `related_jibuns` when one road-name address must be expanded to all linked
parcel/jibun records.

### `sync_metadata`

Small key-value table for ETL state:

```text
key
value
updated_at
```

Common keys:

- `full_archive_path`
- `full_standard_date`
- `last_daily_date`
- `updated_at`

## ETL Flow

### Full Monthly Load

Use the latest "도로명주소 한글" full monthly ZIP as a baseline.

```python
from pykraddr import RoadNameAddressDataClient, RoadNameAddressStore

data = RoadNameAddressDataClient()
zip_path = data.download_latest_full("data/juso/full")

with RoadNameAddressStore("data/juso/rnaddrkor.sqlite") as store:
    counts = store.load_full_archive(zip_path, replace=True)
    print(counts)
```

`load_full_archive()`:

- optionally clears previous rows and metadata
- streams road-name master rows
- streams related-jibun rows
- upserts in batches
- derives legal-dong segments, road-code segments, `pnu`, and
  `building_management_number`
- records full archive metadata

### Daily Incremental Update

Daily files are movement-code deltas.

| Code | Meaning | Store behavior |
| --- | --- | --- |
| `31` | Insert | upsert |
| `34` | Update | upsert |
| `63` | Delete | delete by provider primary key |

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

Important daily-file behavior discovered in live testing:

- Some daily ZIP members contain only `No Data`; parsers intentionally skip
  those members.
- `archive_standard_date()` prefers the archive name, then inner member names.
- `last_daily_date` is set only when a date can be inferred.

## Query Patterns

Lookup by provider composite primary key:

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

Lookup by 26-digit management number:

```python
rows = store.get_road_addresses_by_management_number("1111010100100010000000001")
```

Parcel join by PNU:

```python
road_rows = store.find_road_addresses_by_pnu("1111010100000010000")
jibun_rows = store.find_related_jibuns_by_pnu("1111010100000010000")
```

Regional filtering should start with `sigungu_code` or
`eup_myeon_dong_code`. Avoid filtering only by Korean display names on the full
national table.

## Existing SQLite Upgrade

When an older pykraddr SQLite DB is opened, `RoadNameAddressStore` adds missing
derived columns and indexes. Existing rows loaded before this schema revision
will have empty derived columns until they are reloaded or backfilled.

Backfill without re-downloading:

```python
from pykraddr import RoadNameAddressStore

with RoadNameAddressStore("data/juso/rnaddrkor.sqlite") as store:
    store.backfill_derived_columns()
```

For a production-grade rebuild, prefer loading the latest full monthly archive
and then replaying daily files after that full archive date.

## Codex Maintenance Checklist

When changing this package later:

1. Read `pykraddr/data.py` before changing table columns. Parser column order
   must match the official TXT schema exactly.
2. Keep provider columns as strings. Codes may have leading zeros and must not
   be stored as integers.
3. Keep `pnu` as a string. It is an identifier, not a numeric quantity.
4. Do not drop the provider composite primary keys unless a migration plan and
   duplicate analysis are added.
5. If adding query helpers, prefer indexes over in-Python filtering.
6. If changing daily-update behavior, test all movement codes: `31`, `34`, `63`,
   plus `No Data` daily members.
7. Keep `data/` ignored. The live SQLite DB is multi-GB and should not be
   committed.
8. Before pushing, run:

```powershell
python -m pytest
python -m ruff check .
```

Live load smoke test from the May 2026 implementation:

```text
latest full archive: 202603_도로명주소 한글_전체분.zip
full road rows: 6,416,637
full related-jibun rows: 1,769,370
daily range applied: 2026-04-01 through 2026-05-06
final road rows: 6,418,735
final related-jibun rows: 1,770,362
last_daily_date: 2026-05-06
```
