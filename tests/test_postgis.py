from __future__ import annotations

import pytest

from pykraddr.postgis import (
    DEFAULT_LEGAL_DONG_ALIASES,
    LEGAL_DONG_ALIAS_TABLE,
    LEGAL_DONG_BOUNDARY_TABLE,
    LEGAL_DONG_TABLE,
    boundary_level_from_path,
    make_postgis_metadata,
    resolve_legal_dong_code,
)


def test_boundary_level_from_path() -> None:
    assert boundary_level_from_path("N3A_G0010000.zip") == "sido"
    assert boundary_level_from_path("N3A_G0100000.zip") == "sigungu"
    assert boundary_level_from_path("N3A_G0110000.zip") == "eup_myeon_dong"


def test_make_postgis_metadata_has_fk_and_nullable_unmatched_code() -> None:
    pytest.importorskip("geoalchemy2")

    metadata = make_postgis_metadata(schema="kraddr", srid=5179)
    legal = metadata.tables["kraddr." + LEGAL_DONG_TABLE]
    alias = metadata.tables["kraddr." + LEGAL_DONG_ALIAS_TABLE]
    boundary = metadata.tables["kraddr." + LEGAL_DONG_BOUNDARY_TABLE]

    assert legal.c.legal_dong_code.primary_key
    assert list(alias.c.legal_dong_code.foreign_keys)[0].column is legal.c.legal_dong_code
    assert boundary.c.legal_dong_code.nullable is True
    assert list(boundary.c.legal_dong_code.foreign_keys)[0].column is legal.c.legal_dong_code
    assert boundary.c.geom.type.srid == 5179


def test_resolve_legal_dong_code_uses_csv_master_alias() -> None:
    legal_status = {
        "3611000000": True,
        "2671031000": False,
    }
    aliases = {("sido", "3600000000"): "3611000000"}

    assert resolve_legal_dong_code("sido", "3600000000", legal_status, aliases) == (
        "3611000000",
        "alias_mapped",
    )
    assert resolve_legal_dong_code("eup_myeon_dong", "2671031000", legal_status, aliases) == (
        "2671031000",
        "inactive_legal_dong_code",
    )
    assert resolve_legal_dong_code("sido", "9999999999", legal_status, aliases) == (
        None,
        "missing_legal_dong_code",
    )
    assert DEFAULT_LEGAL_DONG_ALIASES[0]["source_code"] == "3600000000"
    assert DEFAULT_LEGAL_DONG_ALIASES[0]["legal_dong_code"] == "3611000000"
