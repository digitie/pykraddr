# Legal-Dong/PostGIS Load Report

Date: 2026-05-09
Environment: WSL2 Ubuntu, Python 3.12, Docker PostGIS

## Source Data

Legal-dong code source:

- Local file: `/mnt/f/dev/tripmate/dataset/국토교통부_법정동코드_20250805.csv`
- Encoding: CP949
- Columns observed: `법정동코드`, `법정동명`, `폐지여부`
- Rows loaded: `49,861`
- Active rows: `20,555`
- Abolished rows: `29,306`

Boundary ZIP source:

- Directory: `/mnt/f/dev/tripmate/dataset`
- Files:
  - `N3A_G0010000.zip`
  - `N3A_G0100000.zip`
  - `N3A_G0110000.zip`
- SHP attribute code column: `BJCD`
- SHP attribute name column: `NAME`
- Source CRS: Korea 2000 Unified Coordinate System, EPSG:5179-compatible
- Geometry target: PostGIS `MULTIPOLYGON`, SRID `5179`

Public data reference:

- data.go.kr dataset: `국토교통부_전국 법정동_20250807`
- Provider: 국토교통부
- Update cycle: annual
- Next expected registration date on data.go.kr: `2026-08-31`
- The portal describes the dataset as legal regions used by the land
  administration system and sourced from the administrative standard code
  management system.

## Implemented Schema

PostGIS schema name used in validation: `kraddr`

### `legal_dong_codes`

CSV is the master. The table never invents legal-dong codes that are absent
from the CSV/code.go.kr source.

Primary key:

```text
legal_dong_code
```

Important columns:

```text
legal_dong_name
status_name
is_active
previous_legal_dong_code
sido_code
sigungu_code
eup_myeon_dong_code
ri_code
legal_dong_level
source
loaded_at
```

The code segments follow the PDF/code structure:

```text
legal_dong_code(10) = sido(2) + sigungu(3) + eup/myeon/dong(3) + ri(2)
```

### `legal_dong_code_aliases`

Alias table for source systems whose boundary/source code differs from the
CSV legal-dong master code.

Primary key:

```text
source_system
source_layer
source_code
```

FK relationship:

```text
legal_dong_code_aliases.legal_dong_code
  -> legal_dong_codes.legal_dong_code
```

Built-in alias loaded during validation:

| source_system | source_layer | source_code | legal_dong_code | reason |
| --- | --- | --- | --- | --- |
| `vworld_n3a` | `sido` | `3600000000` | `3611000000` | VWorld/N3A sido boundary code differs from code.go.kr legal-dong master |

This keeps `3600000000` out of the CSV master while allowing the source SHP
feature to join to the official `3611000000` legal-dong code.

### `legal_dong_boundaries`

Primary key:

```text
id
```

FK relationship:

```text
legal_dong_boundaries.legal_dong_code
  -> legal_dong_codes.legal_dong_code
```

The original SHP value is always kept in `source_code`. `legal_dong_code` is
the CSV-master code after exact or alias resolution.

Important columns:

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

Mapping statuses:

- `matched`: source code exactly exists in the CSV master and is active.
- `alias_mapped`: source code was mapped through `legal_dong_code_aliases`.
- `inactive_legal_dong_code`: source code exists in the CSV master but is
  abolished/inactive.
- `alias_target_inactive`: alias target exists but is inactive.
- `missing_legal_dong_code`: no exact or alias target exists.

Indexes/constraints verified:

```text
fk_alias_legal_dong_code
fk_boundary_legal_dong_code
legal_dong_boundaries_pkey
legal_dong_code_aliases_pkey
uq_boundary_source_layer_code
idx_legal_dong_boundaries_geom
ix_legal_dong_boundaries_legal_code
ix_legal_dong_boundaries_mapping_status
ix_legal_dong_boundaries_source_code
```

### `legal_dong_boundary_mapping_issues`

View for mismatch review. It returns rows where:

- `legal_dong_code IS NULL`
- matched code is inactive/abolished
- `mapping_status NOT IN ('matched', 'alias_mapped')`

Alias-mapped rows are treated as resolved and do not appear in this issue view.

## WSL2 Full Reload Command

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

## Load Performance Choices

- Legal-dong CSV uses PostgreSQL `COPY FROM STDIN` through `psycopg`.
- Boundary ZIPs are read through GeoPandas. Installing `pyogrio` lets GeoPandas
  use the faster GDAL/Arrow-oriented path when available.
- ZIP extraction happens under WSL2 `/tmp`, not under `/mnt/f`, to avoid slow
  repeated Windows filesystem writes.
- Boundary writes use `GeoDataFrame.to_postgis(..., chunksize=...)`.
- Geometry is normalized to `MULTIPOLYGON` before insert so a single PostGIS
  geometry type can be indexed.
- PostGIS creates the GiST spatial index on `geom`.

For repeated large loads, copy source ZIPs from `/mnt/f/...` into the WSL2 ext4
filesystem first, then load from that path.

## Full Reload Validation Result

PostGIS test flow:

1. Docker PostGIS container started from scratch.
2. `kraddr` schema dropped and recreated.
3. CSV master loaded.
4. Built-in legal-dong alias loaded.
5. All `N3A_*.zip` SHP files loaded.
6. FK, alias, mapping status, and issue view queried.

Loaded counts:

```text
legal_dong_codes: 49,861
active legal_dong_codes: 20,555
inactive legal_dong_codes: 29,306
legal_dong_code_aliases: 1
legal_dong_boundaries: 5,288
FK-mapped boundaries: 5,288
missing legal-dong code boundaries: 0
exact matched boundaries: 5,285
alias-mapped boundaries: 1
inactive legal-dong code boundaries: 2
```

Boundary status counts:

```text
eup_myeon_dong / matched: 5,005
eup_myeon_dong / inactive_legal_dong_code: 2
sido / matched: 16
sido / alias_mapped: 1
sigungu / matched: 264
```

Sejong alias verification:

```text
source_code=3600000000
legal_dong_code=3611000000
mapping_status=alias_mapped
```

## Remaining Findings

| Source File | Layer | Source Code | Source Name | Result |
| --- | --- | --- | --- | --- |
| `N3A_G0110000.zip` | `eup_myeon_dong` | `2671031000` | 일광면 | Present in CSV but inactive/abolished |
| `N3A_G0110000.zip` | `eup_myeon_dong` | `4784035000` | 금수면 | Present in CSV but inactive/abolished |

These satisfy FK integrity because the codes exist in the CSV master, but they
should be filtered out of active-only application queries.

Active-only boundary query:

```sql
SELECT b.*
FROM kraddr.legal_dong_boundaries AS b
JOIN kraddr.legal_dong_codes AS c
  ON b.legal_dong_code = c.legal_dong_code
WHERE c.is_active IS TRUE
  AND b.mapping_status IN ('matched', 'alias_mapped');
```

## Recommendation

Keep the CSV-master plus alias-table design.

- It preserves the official code.go.kr/data.go.kr master as the only source of
  legal-dong truth.
- It keeps source-specific GIS code drift visible in `source_code`.
- It gives every resolvable boundary row a valid FK.
- It keeps unresolved or inactive rows queryable through `mapping_status` and
  the issue view.
