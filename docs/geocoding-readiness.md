# Geocoding and Reverse-Geocoding Readiness

Date: 2026-05-09

This note evaluates the database built by the current pykraddr loaders:

- Juso road-name address Korean TXT data through `RoadNameAddressStore`
- data.go.kr/code.go.kr legal-dong CSV through `PostGISLegalDongStore`
- VWorld/N3A legal-dong boundary SHP ZIPs through GeoPandas/PostGIS

## Current Coverage

### Available

The current loaders can build these useful foundations:

- Legal-dong code master with active/inactive status.
- Legal-dong code aliases for source-system drift.
- Sido, sigungu, and eup/myeon/dong boundary polygons in PostGIS.
- Road-name address master rows from Juso TXT.
- Related jibun rows from Juso TXT.
- PNU derivation from legal-dong code, mountain flag, and lot numbers.
- Road-name address/building management number keys.
- Daily insert/update/delete application for Juso TXT deltas.

### Good For

Administrative reverse lookup:

- Given a point, find containing sido/sigungu/eup-myeon-dong boundary.
- Join the containing boundary to `legal_dong_codes`.
- Use `mapping_status IN ('matched', 'alias_mapped')` and `is_active IS TRUE`
  for active-only administrative results.

Address normalization and key lookup:

- Parse or search road-name address master data by legal-dong code, road-name
  code, building main/sub number, postal code, PNU, and building management
  number.
- Join road-name rows to related jibun rows through management number.

## Not Yet Sufficient For Full Geocoding

The current built DB does **not** yet contain every dataset needed for
production-grade forward geocoding or reverse geocoding.

### Forward Geocoding Gap

Forward geocoding means converting a textual address into coordinates.

The current Juso "도로명주소 한글" TXT master gives identifiers and address
components, but it does not include a point geometry for each building/address.
Therefore, it can identify the address row but cannot return a precise
coordinate by itself.

Needed additions:

- Address/building point table keyed by `building_management_number` or
  `road_address_management_number`.
- Coordinate source, for example Juso coordinate API snapshots, Juso/VWorld
  address-point datasets, building entrance points, or building centroid data.
- Geometry column such as `geom geometry(Point, 5179)` plus optionally WGS84
  lon/lat generated columns or a transformed view.
- Quality/source metadata: source system, coordinate type, observed date,
  confidence, and whether the point is entrance, centroid, parcel centroid, or
  interpolated.

Recommended table:

```text
address_points
  building_management_number PK/FK-ish
  road_address_management_number
  legal_dong_code FK
  pnu
  coordinate_source
  coordinate_type
  geom geometry(Point, 5179)
  lon
  lat
  loaded_at
```

### Reverse Geocoding Gap

Reverse geocoding can mean several levels:

1. Administrative area containing a point.
2. Parcel/jibun containing a point.
3. Nearest or containing building/road-name address.

The current DB supports level 1 down to eup/myeon/dong boundary, but not parcel
or building-level reverse geocoding.

Needed additions:

- Parcel/cadastral polygons keyed by PNU for jibun-level reverse geocoding.
- Building footprints or building register geometry keyed by building
  management number for building-level reverse geocoding.
- Address/building points for nearest-address fallback.
- Road centerlines and road-name codes if road-segment interpolation or
  nearest-road reverse geocoding is required.

Recommended tables:

```text
parcel_boundaries
  pnu PK
  legal_dong_code FK
  mountain_yn
  lot_main_no
  lot_sub_no
  geom geometry(MultiPolygon, 5179)

building_footprints
  building_management_number PK
  legal_dong_code FK
  pnu
  geom geometry(MultiPolygon, 5179)

road_centerlines
  road_name_code
  road_name
  sigungu_code
  geom geometry(MultiLineString, 5179)
```

## Search and Ranking Requirements

A practical geocoder also needs text search and ranking, not only tables.

Recommended additions:

- Normalized Korean address tokens table.
- Road-name and jibun search materialized views.
- PostgreSQL trigram extension (`pg_trgm`) for typo-tolerant search.
- Full-text or token indexes for Korean address components.
- Normalized building name aliases and apartment names.
- Historical/previous address handling using movement/change codes.

Potential views:

```text
geocode_road_address_search
geocode_jibun_address_search
reverse_geocode_admin_area
reverse_geocode_parcel
reverse_geocode_nearest_address_point
```

## Coordinate Reference Systems

The current SHP boundary data is loaded as SRID `5179`. For APIs and web maps,
WGS84 is usually needed.

Recommended:

- Store authoritative geometry in EPSG:5179.
- Add transformed query views for EPSG:4326.
- Return both projected coordinates and lon/lat when useful.

Example:

```sql
SELECT
  legal_dong_code,
  ST_AsGeoJSON(ST_Transform(geom, 4326)) AS geojson
FROM kraddr.legal_dong_boundaries;
```

## Data Quality Checks To Add

Before treating the DB as production geocoding infrastructure, add recurring
checks:

- Every active road-name address has a coordinate.
- Every coordinate joins to an active legal-dong code.
- Every related-jibun PNU has a matching parcel polygon when parcel data is
  loaded.
- Boundary polygons are valid: `ST_IsValid(geom)`.
- Boundary polygons have expected containment hierarchy:
  eup/myeon/dong within sigungu, sigungu within sido.
- Alias mappings are reviewed and source-specific, never inserted into the
  CSV-master table.
- Daily address deltas do not create orphan coordinate rows.

## Bottom Line

The current DB is a solid administrative-code and boundary foundation. It can
support legal-dong lookups, administrative reverse geocoding, and address-key
normalization.

It is not yet complete for precise forward geocoding or building/parcel-level
reverse geocoding. The highest-priority additions are:

1. Address/building point coordinates keyed by building management number.
2. Parcel polygons keyed by PNU.
3. Building footprints keyed by building management number.
4. Search/ranking materialized views and text indexes.
