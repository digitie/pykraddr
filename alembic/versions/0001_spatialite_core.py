"""Create SQLite/SpatiaLite geocoding core tables."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "0001_spatialite_core"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "juso_address_points",
        sa.Column("point_id", sa.String(length=180), primary_key=True),
        sa.Column("source", sa.String(length=300), nullable=False),
        sa.Column("source_dataset", sa.String(length=80), nullable=False),
        sa.Column("source_key", sa.String(length=180), nullable=False),
        sa.Column("source_priority", sa.Integer(), nullable=False),
        sa.Column("coordinate_role", sa.String(length=40), nullable=False),
        sa.Column("building_management_number", sa.String(length=30)),
        sa.Column("legal_dong_code", sa.String(length=10)),
        sa.Column("sido_name", sa.String(length=40), nullable=False),
        sa.Column("sigungu_name", sa.String(length=40), nullable=False),
        sa.Column("eup_myeon_dong_name", sa.String(length=40), nullable=False),
        sa.Column("road_name_code", sa.String(length=12)),
        sa.Column("road_name", sa.String(length=80), nullable=False),
        sa.Column("underground_yn", sa.String(length=1), nullable=False),
        sa.Column("building_main_no", sa.String(length=10), nullable=False),
        sa.Column("building_sub_no", sa.String(length=10), nullable=False),
        sa.Column("postal_code", sa.String(length=5), nullable=False),
        sa.Column("road_address", sa.String(length=300), nullable=False),
        sa.Column("parcel_address", sa.String(length=300), nullable=False),
        sa.Column("building_name", sa.String(length=200), nullable=False),
        sa.Column("building_use", sa.String(length=100), nullable=False),
        sa.Column("x", sa.Float(), nullable=False),
        sa.Column("y", sa.Float(), nullable=False),
        sa.Column("srid", sa.Integer(), nullable=False),
        sa.Column("geom_wkt", sa.String(), nullable=False),
        sa.Column("geom_wkb", sa.LargeBinary(), nullable=False),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_json", sa.JSON(), nullable=False),
        sa.UniqueConstraint(
            "source_dataset",
            "source_key",
            "coordinate_role",
            name="uq_juso_point_source_role",
        ),
    )
    op.create_index("ix_juso_points_source", "juso_address_points", ["source"])
    op.create_index(
        "ix_juso_points_dataset_role",
        "juso_address_points",
        ["source_dataset", "coordinate_role"],
    )
    op.create_index("ix_juso_points_priority", "juso_address_points", ["source_priority"])
    op.create_index(
        "ix_juso_points_building_mgmt",
        "juso_address_points",
        ["building_management_number"],
    )
    op.create_index("ix_juso_points_legal_dong", "juso_address_points", ["legal_dong_code"])
    op.create_index(
        "ix_juso_points_road_lookup",
        "juso_address_points",
        ["road_name_code", "underground_yn", "building_main_no", "building_sub_no"],
    )
    op.create_index("ix_juso_points_road_name", "juso_address_points", ["road_name"])
    op.create_index("ix_juso_points_postal_code", "juso_address_points", ["postal_code"])
    op.create_index(
        "ix_juso_points_postal_lookup",
        "juso_address_points",
        [
            "postal_code",
            "road_name_code",
            "building_main_no",
            "building_sub_no",
            "source_priority",
        ],
    )
    op.create_index(
        "ix_juso_points_listing_order",
        "juso_address_points",
        [
            "source_priority",
            "road_name_code",
            "building_main_no",
            "building_sub_no",
            "point_id",
        ],
    )
    op.create_index("ix_juso_points_xy", "juso_address_points", ["x", "y"])
    op.create_index("ix_juso_points_road_address", "juso_address_points", ["road_address"])
    op.create_index("ix_juso_points_parcel_address", "juso_address_points", ["parcel_address"])
    op.create_index("ix_juso_points_building_name", "juso_address_points", ["building_name"])

    op.create_table(
        "juso_boundary_polygons",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_system", sa.String(length=80), nullable=False),
        sa.Column("source_file", sa.String(length=260), nullable=False),
        sa.Column("source_layer", sa.String(length=80), nullable=False),
        sa.Column("source_code", sa.String(length=30), nullable=False),
        sa.Column("source_name", sa.String(length=200), nullable=False),
        sa.Column("legal_dong_code", sa.String(length=10)),
        sa.Column("boundary_level", sa.String(length=30), nullable=False),
        sa.Column("mapping_status", sa.String(length=40), nullable=False),
        sa.Column("srid", sa.Integer(), nullable=False),
        sa.Column("geom_wkt", sa.String(), nullable=False),
        sa.Column("geom_wkb", sa.LargeBinary(), nullable=False),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_json", sa.JSON(), nullable=False),
        sa.UniqueConstraint(
            "source_system",
            "source_layer",
            "source_code",
            name="uq_juso_boundary_source",
        ),
    )
    op.create_index(
        "ix_juso_boundaries_legal_code",
        "juso_boundary_polygons",
        ["legal_dong_code"],
    )
    op.create_index("ix_juso_boundaries_source_code", "juso_boundary_polygons", ["source_code"])
    op.create_index("ix_juso_boundaries_layer", "juso_boundary_polygons", ["source_layer"])
    op.create_index("ix_juso_boundaries_status", "juso_boundary_polygons", ["mapping_status"])

    op.create_table(
        "juso_spatial_metadata",
        sa.Column("key", sa.String(length=100), primary_key=True),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS juso_address_fts
        USING fts5(
            road_name,
            road_address,
            parcel_address,
            building_name,
            content='juso_address_points',
            content_rowid='rowid',
            tokenize='trigram'
        )
        """
    )
    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS juso_address_points_fts_ai
        AFTER INSERT ON juso_address_points
        BEGIN
            INSERT INTO juso_address_fts
                (rowid, road_name, road_address, parcel_address, building_name)
            VALUES (
                new.rowid,
                new.road_name,
                new.road_address,
                new.parcel_address,
                new.building_name
            );
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS juso_address_points_fts_ad
        AFTER DELETE ON juso_address_points
        BEGIN
            INSERT INTO juso_address_fts
                (juso_address_fts, rowid, road_name, road_address, parcel_address, building_name)
            VALUES (
                'delete',
                old.rowid,
                old.road_name,
                old.road_address,
                old.parcel_address,
                old.building_name
            );
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS juso_address_points_fts_au
        AFTER UPDATE ON juso_address_points
        BEGIN
            INSERT INTO juso_address_fts
                (juso_address_fts, rowid, road_name, road_address, parcel_address, building_name)
            VALUES (
                'delete',
                old.rowid,
                old.road_name,
                old.road_address,
                old.parcel_address,
                old.building_name
            );
            INSERT INTO juso_address_fts
                (rowid, road_name, road_address, parcel_address, building_name)
            VALUES (
                new.rowid,
                new.road_name,
                new.road_address,
                new.parcel_address,
                new.building_name
            );
        END
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS juso_address_points_fts_au")
    op.execute("DROP TRIGGER IF EXISTS juso_address_points_fts_ad")
    op.execute("DROP TRIGGER IF EXISTS juso_address_points_fts_ai")
    op.execute("DROP TABLE IF EXISTS juso_address_fts")
    for index_name in _POINT_INDEXES:
        op.drop_index(index_name, table_name="juso_address_points")
    for index_name in _BOUNDARY_INDEXES:
        op.drop_index(index_name, table_name="juso_boundary_polygons")
    op.drop_table("juso_spatial_metadata")
    op.drop_table("juso_boundary_polygons")
    op.drop_table("juso_address_points")


_POINT_INDEXES: Sequence[str] = (
    "ix_juso_points_source",
    "ix_juso_points_dataset_role",
    "ix_juso_points_priority",
    "ix_juso_points_building_mgmt",
    "ix_juso_points_legal_dong",
    "ix_juso_points_road_lookup",
    "ix_juso_points_road_name",
    "ix_juso_points_postal_code",
    "ix_juso_points_postal_lookup",
    "ix_juso_points_listing_order",
    "ix_juso_points_xy",
    "ix_juso_points_road_address",
    "ix_juso_points_parcel_address",
    "ix_juso_points_building_name",
)
_BOUNDARY_INDEXES: Sequence[str] = (
    "ix_juso_boundaries_legal_code",
    "ix_juso_boundaries_source_code",
    "ix_juso_boundaries_layer",
    "ix_juso_boundaries_status",
)
