"""The game versions the app supports: TBC Anniversary and WoW: Forever.

Alt Army runs on both clients and writes the same `AltArmy_TBC.lua` on each; only the WoW flavor folder
(`_anniversary_`, `_classic_beta_`) tells them apart. In local mode each version has its own SQLite file.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from . import db
from .engine import AH_CUT, MAIL_POSTAGE

GameVersionKey = Literal["tbc", "forever"]
DATA_DIR = Path("data")


@dataclass(frozen=True)
class GameVersion:
    key: GameVersionKey
    label: str
    wago_product: str  # wago.tools product whose DB2 tables describe this client
    default_build: str  # pinned build ingested unless another (or "latest") is asked for
    flavor_folders: tuple[str, ...]  # WoW install subfolders whose WTF holds this client's SavedVariables
    data_dir: Path  # hand-maintained CSVs: disenchant.csv, vendor_items.csv
    db_path: Path  # local-mode SQLite file
    ah_cut: float = AH_CUT
    mail_postage: int = MAIL_POSTAGE  # copper per attachment

    @property
    def disenchant_csv(self) -> Path:
        return self.data_dir / "disenchant.csv"

    @property
    def vendor_csv(self) -> Path:
        return self.data_dir / "vendor_items.csv"


def db_path(key: str, data_dir: Path = DATA_DIR) -> Path:
    """The local-mode database for a version, e.g. data/altarmy-profit-tbc.db."""
    return data_dir / f"altarmy-profit-{key}.db"


VERSIONS: dict[str, GameVersion] = {
    "forever": GameVersion(
        key="forever",
        label="WoW: Forever",
        wago_product="wow_classic_beta",
        default_build="1.60.1.69913",
        flavor_folders=("_classic_beta_",),
        data_dir=DATA_DIR / "forever",
        db_path=db_path("forever"),
    ),
    "tbc": GameVersion(
        key="tbc",
        label="TBC Anniversary",
        wago_product="wow_anniversary",
        default_build="2.5.6.69795",
        flavor_folders=("_anniversary_",),
        data_dir=DATA_DIR / "tbc",
        db_path=db_path("tbc"),
    ),
}
DEFAULT_VERSION: GameVersionKey = "forever"


def get(key: str) -> GameVersion:
    """The version named `key`; ValueError listing the known ones otherwise."""
    try:
        return VERSIONS[key]
    except KeyError:
        raise ValueError(f"unknown game version {key!r}; expected one of {', '.join(VERSIONS)}") from None


def version_of_build(build: str) -> GameVersionKey:
    """Which version a DB2 build belongs to: 2.x is TBC, anything else (1.60.x) is Forever."""
    return "tbc" if build.startswith("2.") else "forever"


def migrate_legacy_db(
    legacy: Path = db.LEGACY_DB, versions: dict[str, GameVersion] = VERSIONS
) -> Path | None:
    """Rename the pre-versions database to its version's file, picked from the build it holds (no build
    means Forever, the only version back then). Returns the new path; None if there was nothing to move or
    that version already has a database."""
    if not legacy.is_file():
        return None
    conn = db.connect(legacy)
    try:
        db.init_schema(conn)
        build = db.get_meta(conn, "build")
    finally:
        conn.close()
    target = versions[version_of_build(build or "")].db_path
    if target.exists():
        return None
    legacy.rename(target)
    return target
