"""Explicit, atomic catalogue bootstrap; never creates or modifies legacy tables."""
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
import unicodedata

from sqlalchemy import func, inspect, select
from sqlalchemy.engine import Engine

from app.db.database import Base
from app.db.models import (
    Business, Brand, CatalogueEvent, CatalogueIdempotency, CatalogueMigration,
    Plant, Region, normalize_brand_name,
)


DEFAULT_SEED_PATH = Path(__file__).resolve().parents[2] / "config" / "plants.json"
CATALOGUE_TABLES = [
    Brand.__table__, Region.__table__, Plant.__table__,
    CatalogueEvent.__table__, CatalogueIdempotency.__table__, CatalogueMigration.__table__,
]
NZ_REGIONS = (
    "central_west", "west", "south_east", "south", "central_east", "north",
    "central_south", "east", "north_west", "north_shore",
)
REGION_MAPPING = {
    slug: {
        "id": f"nz_{slug}", "name": slug.replace("_", " ").title(),
        "country_code": "NZ", "administrative_area": "Auckland",
        "timezone": "Pacific/Auckland", "calibration_status": "nz_baseline",
    }
    for slug in NZ_REGIONS
}
REGION_MAPPING["warangal"] = {
    "id": "in_telangana_warangal", "name": "Warangal", "country_code": "IN",
    "administrative_area": "Telangana", "timezone": "Asia/Kolkata",
    "calibration_status": "uncalibrated",
}


class CatalogueMigrationError(ValueError):
    """Invalid seed or ambiguous pre-existing catalogue state."""


@dataclass(frozen=True)
class CatalogueMigrationResult:
    version: int
    applied: bool
    brands: int = 0
    regions: int = 0
    plants: int = 0


def _required_string(row, field, index, limit):
    value = row.get(field)
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise CatalogueMigrationError(f"Seed plant {index}: invalid {field}")
    return value


def _load_seed(path):
    # The ledger is checked first, so repeat startups do not even read this file.
    try:
        rows = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CatalogueMigrationError(f"Cannot read catalogue seed: {exc}") from exc
    if not isinstance(rows, list) or not rows:
        raise CatalogueMigrationError("Catalogue seed must be a nonempty array")
    brands, regions, plants = {}, {}, []
    ids, brand_ids = set(), {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise CatalogueMigrationError(f"Seed plant {index}: expected object")
        plant = {
            field: _required_string(row, field, index, limit)
            for field, limit in [("id", 100), ("name", 200), ("address", 500)]
        }
        if plant["id"] in ids:
            raise CatalogueMigrationError(f"Duplicate plant id: {plant['id']}")
        ids.add(plant["id"])
        brand = _required_string(row, "brand", index, 200)
        name_key = normalize_brand_name(brand)
        ascii_key = unicodedata.normalize("NFKD", name_key).encode("ascii", "ignore").decode()
        slug = re.sub(r"[^a-z0-9]+", "_", ascii_key).strip("_")
        brand_id = f"brand_{slug}"
        if not slug or len(brand_id) > 100:
            raise CatalogueMigrationError(f"Invalid brand slug: {brand}")
        if brand_id in brand_ids and brand_ids[brand_id] != name_key:
            raise CatalogueMigrationError(f"Brand slug collision: {brand}")
        brand_ids[brand_id] = name_key
        brands.setdefault(name_key, {"id": brand_id, "name": brand.strip(), "name_key": name_key})
        legacy_region = _required_string(row, "region", index, 100)
        if legacy_region not in REGION_MAPPING:
            raise CatalogueMigrationError(f"Unknown legacy region: {legacy_region}")
        region = REGION_MAPPING[legacy_region]
        regions[region["id"]] = dict(region)
        for field, limit in [("lat", 90), ("lng", 180)]:
            value = row.get(field)
            if (
                isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or not -limit <= value <= limit
            ):
                raise CatalogueMigrationError(f"Seed plant {index}: invalid {field}")
            plant[field] = value
        if not isinstance(row.get("active", True), bool):
            raise CatalogueMigrationError(f"Seed plant {index}: invalid active")
        mixes = row.get("supported_mix_codes", ["GP", "HE", "RE"])
        if (
            not isinstance(mixes, list) or not mixes
            or any(not isinstance(code, str) or code not in ("GP", "HE", "RE") for code in mixes)
            or len(set(mixes)) != len(mixes)
        ):
            raise CatalogueMigrationError(f"Seed plant {index}: invalid supported_mix_codes")
        plant.update(
            brand_id=brand_id, region_id=region["id"],
            active=row.get("active", True), supported_mix_codes=mixes,
        )
        plants.append(plant)
    return list(brands.values()), list(regions.values()), plants


def migrate_catalogue(engine: Engine, seed_path: Path | None = None) -> CatalogueMigrationResult:
    """Apply version 1 in a dedicated transaction, or return an unapplied result.

    Only an Engine is accepted: this function never commits a caller's Session or
    Connection. Seed validation precedes DDL; existing unledgered data is rejected.
    Result counts describe imported records, and are zero for a repeat invocation.
    """
    if not isinstance(engine, Engine):
        raise TypeError("migrate_catalogue requires an Engine, not an active transaction")
    with engine.begin() as connection:
        if connection.dialect.name == "sqlite":
            # sqlite3 legacy transaction mode does not make DDL transactional.
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        existing = set(inspect(connection).get_table_names())
        ledger = CatalogueMigration.__table__
        if ledger.name in existing:
            versions = set(connection.execute(select(ledger.c.version)).scalars())
            if versions - {1}:
                raise CatalogueMigrationError("Unsupported catalogue migration version")
            if 1 in versions:
                missing = {table.name for table in CATALOGUE_TABLES} - existing
                if missing:
                    raise CatalogueMigrationError(f"Ledger has missing tables: {sorted(missing)}")
                return CatalogueMigrationResult(version=1, applied=False)
        for table in CATALOGUE_TABLES:
            if table.name in existing and connection.scalar(
                select(func.count()).select_from(table)
            ):
                raise CatalogueMigrationError(
                    f"Nonempty catalogue table without migration ledger: {table.name}"
                )
        brands, regions, plants = _load_seed(
            seed_path if seed_path is not None else DEFAULT_SEED_PATH
        )
        from app.db.geography import BusinessCountry, Country, State, City

        Base.metadata.create_all(connection, tables=[
            Business.__table__, Country.__table__, BusinessCountry.__table__, State.__table__, City.__table__,
        ])
        Base.metadata.create_all(connection, tables=CATALOGUE_TABLES)
        connection.execute(Brand.__table__.insert(), brands)
        connection.execute(Region.__table__.insert(), regions)
        connection.execute(Plant.__table__.insert(), plants)
        connection.execute(ledger.insert().values(version=1))
        return CatalogueMigrationResult(
            version=1, applied=True, brands=len(brands), regions=len(regions), plants=len(plants)
        )
