import urllib.error
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, select

from altarmy_profit import altarmy, auth, db, ingest, prices, schema, service, store, users
from altarmy_profit.altarmy import Character, Profession
from altarmy_profit.api import create_app
from altarmy_profit.versions import GameVersion

from .conftest import FOREVER, ME, SV_DIR, set_prices
from .test_altarmy import ALTARMY_SV
from .test_auctionator import _entry, _saved_variables
from .test_auth import FakeVerifier


@pytest.fixture
def client(
    tmp_path: Path, vendor_csv: Path, game_versions: dict[str, GameVersion], database: db.Database
) -> TestClient:
    """Asks about Forever unless a request passes another game_version; shares the `conn` fixture's
    database."""
    app = create_app(
        game_versions,
        database=database,
        cache_dir=tmp_path / "cache",
        static_dir=tmp_path / "nodist",
        wow_roots=[tmp_path / "World of Warcraft"],  # where the `wow_root` fixture puts one
        mode="local",
    )
    c = TestClient(app)
    c.params = c.params.set("game_version", "forever")
    return c


def with_tailor(conn: Connection) -> None:
    """Store the Alt Army test characters and select the realm/faction of the one who knows the robe."""
    store.save_characters(conn, ME, FOREVER, altarmy.parse_characters(ALTARMY_SV))
    service.select(conn, ME, FOREVER, "Classic Beta PvE", "Horde")


@pytest.fixture
def priced(db2_paths: dict[str, Path], conn: Connection) -> Connection:
    """The client's database with game data, prices linen=20, thread=100 on Classic Beta PvE's auction
    house and a selected tailor there who knows the Green Robe."""
    ingest.build_db(db2_paths, conn, FOREVER)
    set_prices(conn, {1: 20, 2: 100})
    with_tailor(conn)
    return conn


def test_empty_db(client: TestClient, database: db.Database) -> None:
    status = client.get("/api/status").json()
    assert status["recipes"] == 0
    assert status["build"] is None
    assert status["last_auctionator_import"] is None
    assert status["db_path"] == database.display_url
    assert (status["characters"], status["selection"], status["data_version"]) == (0, None, 0)
    assert status["warnings"] == ["No Alt Army file found. Pick AltArmy_TBC.lua on the Manage tab."]
    assert client.get("/api/characters").json() == {"groups": [], "selection": None}
    assert client.get("/api/rank").json()["results"] == []


def test_rank_known_recipes(client: TestClient, priced: Connection) -> None:
    body = client.get("/api/rank").json()
    (r,) = body["results"]
    assert r["recipe"] == "Green Robe"
    assert r["profession"] == "Tailoring"
    assert (r["crafters"], r["crafter"]) == (["Tailor Guy"], "Tailor Guy")
    assert body["classes"] == {"Tailor Guy": "MAGE"}
    assert (r["output_name"], r["output_count"]) == ("Green Robe", 1)
    assert (r["cost"], r["revenue"], r["profit"]) == (300, 500, 200)
    assert r["roi"] == pytest.approx(2 / 3)
    assert r["best_exit"] == "vendor"
    assert [(s["action"], s["name"], s["quantity"], s["value"], s["via"]) for s in r["steps"]] == [
        ("buy", "Linen Cloth", 10, -200, "ah"),
        ("buy", "Coarse Thread", 1, -100, "ah"),
        ("craft", "Green Robe", 1, 0, "Green Robe"),
        ("sell", "Green Robe", 1, 500, "vendor"),
    ]
    assert {"kind": "vendor", "value": 500, "materials": [], "postage": 0, "mail_to": ""} in r["exits"]
    assert (r["postage"], r["mail_to"]) == (0, "")
    tree = r["tree"]
    assert (tree["item_id"], tree["quantity"], tree["cost"], tree["via"], tree["crafts"]) == (
        3,
        1,
        300,
        "Green Robe",
        1,
    )
    assert [(n["item_id"], n["quantity"], n["cost"], n["source"], n["inputs"]) for n in tree["inputs"]] == [
        (1, 10, 200, "ah", []),
        (2, 1, 100, "ah", []),
    ]


def test_rank_buys_reagents_from_vendors(
    client: TestClient, db2_paths: dict[str, Path], conn: Connection, vendor_csv: Path
) -> None:
    ingest.build_db(db2_paths, conn, FOREVER, vendor_csv=vendor_csv)
    set_prices(conn, {1: 20})  # thread has no AH price, but vendors sell it for 11c
    with_tailor(conn)
    body = client.get("/api/rank").json()
    (r,) = body["results"]
    assert r["cost"] == 200 + 11
    assert (r["steps"][1]["name"], r["steps"][1]["via"]) == ("Coarse Thread", "vendor")
    assert r["tree"]["inputs"][1]["source"] == "vendor"
    assert (body["items"]["2"]["vendor_price"], body["items"]["1"]["vendor_price"]) == (11, None)


def with_enchanter(conn: Connection) -> None:
    """Add an enchanter (who can't tailor) to the tailor's realm/faction."""
    enchanter = Character(
        "Classic Beta PvE", "Enchy", "Horde", "PRIEST", 20, (Profession("Enchanting", 60, 75, frozenset()),)
    )
    store.save_characters(conn, ME, FOREVER, [*altarmy.parse_characters(ALTARMY_SV), enchanter])


def add_disenchant(conn: Connection, chance: float, min_count: int, max_count: int) -> None:
    """Green armor disenchants into linen."""
    conn.execute(
        schema.disenchant.insert().values(
            game_version=FOREVER,
            item_class=4,
            quality=2,
            min_ilvl=0,
            max_ilvl=1000,
            result_item_id=1,
            chance=chance,
            min_count=min_count,
            max_count=max_count,
        )
    )


def test_rank_sends_disenchant_materials(client: TestClient, priced: Connection) -> None:
    add_disenchant(priced, 0.5, 1, 3)  # robe -> 1-3 linen
    with_enchanter(priced)
    body = client.get("/api/rank").json()
    (r,) = body["results"]
    (de,) = [e for e in r["exits"] if e["kind"] == "disenchant"]
    assert de["materials"] == [
        {"item_id": 1, "name": "Linen Cloth", "chance": 0.5, "min_count": 1, "max_count": 3, "value": 19}
    ]
    assert all(e["materials"] == [] for e in r["exits"] if e["kind"] != "disenchant")


def test_rank_mails_disenchants_to_an_enchanter(client: TestClient, priced: Connection) -> None:
    add_disenchant(priced, 1.0, 100, 100)  # robe -> 100 linen
    (r,) = client.get("/api/rank").json()["results"]
    assert r["best_exit"] == "vendor"  # nobody on the realm can disenchant

    with_enchanter(priced)
    (r,) = client.get("/api/rank").json()["results"]
    assert (r["best_exit"], r["postage"], r["mail_to"], r["cost"]) == ("disenchant", 30, "Enchy", 330)
    assert ("mail", "Green Robe", 1, -30, "Enchy", "Tailor Guy") in [
        (s["action"], s["name"], s["quantity"], s["value"], s["via"], s["who"]) for s in r["steps"]
    ]
    assert [(n["crafter"], n["mail_to"], n["postage"]) for n in r["tree"]["inputs"]] == [
        ("Tailor Guy", "", 0),
        ("Tailor Guy", "", 0),
    ]


def test_rank_sends_reagents_and_item_details(client: TestClient, priced: Connection) -> None:
    body = client.get("/api/rank").json()
    (r,) = body["results"]
    assert r["reagents"] == [{"item_id": 1, "count": 10}, {"item_id": 2, "count": 1}]
    items = body["items"]
    assert set(items) == {"1", "2", "3"}  # output and reagents; JSON object keys are strings
    assert items["1"]["ah_price"] == 20
    assert items["3"] == {
        "id": 3,
        "name": "Green Robe",
        "quality": 2,
        "class_id": 4,
        "subclass_name": "Cloth",
        "inventory_type": 20,
        "bonding": 2,
        "item_delay": 0,
        "container_slots": 0,
        "required_level": 12,
        "required_skill": "Tailoring",
        "required_skill_rank": 50,
        "description": "Soft and green.",
        "sell_price": 500,
        "icon": "inv_chest_cloth_39",
        "ah_price": None,
        "vendor_price": None,
    }


def test_rank_lists_options_and_evaluate_applies_choices(
    client: TestClient, db2_paths: dict[str, Path], conn: Connection, vendor_csv: Path
) -> None:
    ingest.build_db(db2_paths, conn, FOREVER, vendor_csv=vendor_csv)
    set_prices(conn, {1: 20, 2: 100})  # vendors sell thread for 11c
    with_tailor(conn)
    (r,) = client.get("/api/rank").json()["results"]
    assert r["tree"]["options"] == []
    assert r["tree"]["inputs"][1]["options"] == [
        {"key": "vendor", "cost": 11, "source": "vendor", "via": "", "crafter": ""},
        {"key": "ah", "cost": 100, "source": "ah", "via": "", "crafter": ""},
    ]
    assert r["sell_options"] == [{"kind": "vendor", "profit": 500 - 211}]

    body = {"recipe_id": r["recipe_id"], "choices": {"r.1": "ah"}}
    got = client.post("/api/evaluate", json=body).json()
    assert (got["result"]["cost"], got["result"]["tree"]["inputs"][1]["source"]) == (300, "ah")
    assert set(got["items"]) == {"1", "2", "3"}
    assert client.post("/api/evaluate", json={"recipe_id": 999, "choices": {}}).status_code == 404
    only_ah = {**body, "exits": ["ah"]}  # the robe has no AH price
    assert client.post("/api/evaluate", json=only_ah).status_code == 404


def test_ah_blocked_items_are_never_sold_on_the_ah(client: TestClient, priced: Connection) -> None:
    set_prices(priced, {3: 1000})  # the robe sells for 950 on the AH, 500 at a vendor
    assert client.get("/api/ah-blocked").json() == {"items": [], "details": {}}
    (r,) = client.get("/api/rank").json()["results"]
    assert r["best_exit"] == "ah"

    blocked = client.put("/api/ah-blocked/3").json()
    assert [i["item_id"] for i in blocked["items"]] == [3]
    assert blocked["items"][0]["added_at"]
    robe = blocked["details"]["3"]
    assert (robe["name"], robe["ah_price"]) == ("Green Robe", 1000)
    assert client.get("/api/ah-blocked").json() == blocked
    (r,) = client.get("/api/rank").json()["results"]
    assert (r["best_exit"], [e["kind"] for e in r["exits"]]) == ("vendor", ["vendor"])
    got = client.post("/api/evaluate", json={"recipe_id": r["recipe_id"], "choices": {"sell": "ah"}}).json()
    assert got["result"]["best_exit"] == "vendor"

    assert client.delete("/api/ah-blocked/3").json() == {"items": [], "details": {}}
    (r,) = client.get("/api/rank").json()["results"]
    assert r["best_exit"] == "ah"


def test_rank_filters_and_validation(client: TestClient, priced: Connection) -> None:
    def total(**params: str | int | float | list[str]) -> int:
        body = client.get("/api/rank", params=params).json()
        assert len(body["results"]) == body["total"]
        return int(body["total"])

    assert total() == 1  # cost 300, profit 200, roi 2/3, sold to a vendor
    assert total(min_profit=201) == 0
    assert total(min_profit=200, max_profit=200, min_cost=300, max_cost=300) == 1
    assert total(max_profit=199) == 0
    assert total(min_cost=301) == 0
    assert total(max_cost=299) == 0
    assert total(min_roi=0.6, max_roi=0.7) == 1
    assert total(min_roi=0.7) == 0
    assert total(max_roi=0.6) == 0
    assert total(exits=["ah", "disenchant"]) == 0
    assert total(exits=["vendor"]) == 1
    assert client.get("/api/rank", params={"exits": "trade"}).status_code == 422
    assert client.get("/api/rank", params={"top": 0}).status_code == 422
    service.select(priced, ME, FOREVER, "Dreamscythe", "Horde")  # cooks only
    assert total() == 0


def test_update_game_data_invalidates_cache(
    client: TestClient, db2_paths: dict[str, Path], conn: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ingest, "latest_build", lambda product: "9.9.9.1")
    monkeypatch.setattr(ingest, "download_all", lambda build, cache_dir: db2_paths)
    set_prices(conn, {1: 20, 2: 100})
    with_tailor(conn)
    assert client.get("/api/rank").json()["results"] == []  # prime the cache: no recipes yet

    res = client.post("/api/game-data/update")
    assert res.status_code == 200
    assert res.json()["build"] == "9.9.9.1"
    assert res.json()["updated"] is True
    assert res.json()["items"] == 3
    assert res.json()["vendor_items"] == 2
    assert client.get("/api/status").json()["build"] == "9.9.9.1"
    assert len(client.get("/api/rank").json()["results"]) == 1


def test_update_game_data_only_if_new(
    client: TestClient, db2_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    downloads: list[str] = []

    def fake_download_all(build: str, cache_dir: Path) -> dict[str, Path]:
        downloads.append(build)
        return db2_paths

    monkeypatch.setattr(ingest, "latest_build", lambda product: "9.9.9.1")
    monkeypatch.setattr(ingest, "download_all", fake_download_all)

    first = client.post("/api/game-data/update", params={"only_if_new": True}).json()
    assert first["updated"] is True
    same = client.post("/api/game-data/update", params={"only_if_new": True}).json()
    assert same == {**first, "updated": False}  # counts reflect the database as it stands
    assert downloads == ["9.9.9.1"]

    client.post("/api/game-data/update")  # without the flag it always rebuilds
    assert downloads == ["9.9.9.1", "9.9.9.1"]

    monkeypatch.setattr(ingest, "latest_build", lambda product: "9.9.9.2")
    assert client.post("/api/game-data/update", params={"only_if_new": True}).json()["updated"] is True
    assert client.get("/api/status").json()["build"] == "9.9.9.2"


def test_update_game_data_network_error(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(product: str) -> str:
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(ingest, "latest_build", fail)
    res = client.post("/api/game-data/update")
    assert res.status_code == 502
    assert "offline" in res.json()["detail"]


def test_auctionator_files_default(
    client: TestClient, conn: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = [Path(r"W\_classic_\A.lua"), Path(r"W\_classic_beta_\A.lua")]
    monkeypatch.setattr(prices, "find_auctionator_files", lambda roots, flavors: files)
    body = client.get("/api/auctionator/files").json()
    assert body == {"files": [str(f) for f in files], "default": str(files[0])}
    users.update_sync(conn, ME, FOREVER, auctionator_path=str(files[1]))
    assert client.get("/api/auctionator/files").json()["default"] == str(files[1])


def test_rank_include_unlearned(client: TestClient, priced: Connection) -> None:
    novice = Character("Realm", "Novice", "Horde", "MAGE", 5, (Profession("Tailoring", 1, 75, frozenset()),))
    store.save_characters(priced, ME, FOREVER, [novice])
    set_prices(priced, {1: 20, 2: 100}, realm="Realm")
    assert client.get("/api/rank").json()["results"] == []
    (r,) = client.get("/api/rank", params={"include_unlearned": True}).json()["results"]
    assert (r["recipe"], r["crafters"]) == ("Green Robe", [])


def test_rank_and_evaluate_without_trivial_recipes(client: TestClient, priced: Connection) -> None:
    veteran = Character(
        "Realm", "Veteran", "Horde", "MAGE", 60, (Profession("Tailoring", 60, 150, frozenset({900})),)
    )
    store.save_characters(priced, ME, FOREVER, [veteran])  # the robe is grey from 60
    set_prices(priced, {1: 20, 2: 100}, realm="Realm")
    (r,) = client.get("/api/rank").json()["results"]
    grey = client.get("/api/rank", params={"include_trivial": False}).json()
    assert (grey["results"], grey["total"]) == ([], 0)
    body = {"recipe_id": r["recipe_id"], "choices": {}}
    assert client.post("/api/evaluate", json=body).status_code == 200
    assert client.post("/api/evaluate", json={**body, "include_trivial": False}).status_code == 404


def test_status_syncs_addon_files_and_selection_switches_realm(
    client: TestClient, db2_paths: dict[str, Path], conn: Connection, wow_root: Path
) -> None:
    ingest.build_db(db2_paths, conn, FOREVER)
    status = client.get("/api/status").json()
    assert status["altarmy_path"] == str(wow_root / SV_DIR / "AltArmy_TBC.lua")
    assert status["auctionator_path"] == str(wow_root / SV_DIR / "Auctionator.lua")
    assert (status["characters"], status["data_version"], status["warnings"]) == (4, 1, [])
    assert status["selection"] == {"realm": "Dreamscythe", "faction": "Horde"}
    assert status["auctionator_realm"] == "Dreamscythe Horde"
    assert status["last_altarmy_sync"] is not None
    assert status["last_auctionator_sync"] is not None
    assert client.get("/api/status").json()["data_version"] == 1  # files unchanged

    body = client.get("/api/characters").json()
    assert [(g["realm"], g["faction"], len(g["characters"])) for g in body["groups"]] == [
        ("Classic Beta PvE", "Alliance", 1),
        ("Classic Beta PvE", "Horde", 1),
        ("Dreamscythe", "Horde", 2),
    ]
    assert body["groups"][1]["characters"] == [
        {
            "name": "Tailor Guy",
            "class_file": "MAGE",
            "level": 20,
            "professions": [
                {"name": "Cooking", "rank": 1, "max_rank": 75, "recipes": 0},
                {"name": "Tailoring", "rank": 50, "max_rank": 75, "recipes": 1},
            ],
        }
    ]
    assert body["selection"] == {"realm": "Dreamscythe", "faction": "Horde"}
    assert client.get("/api/rank").json()["results"] == []  # Dreamscythe only cooks

    res = client.put("/api/selection", json={"realm": "Classic Beta PvE", "faction": "Horde"})
    assert res.status_code == 200
    assert res.json()["auctionator_realm"] == "ClassicBetaPvE"
    assert res.json()["data_version"] == 2
    (r,) = client.get("/api/rank").json()["results"]
    assert (r["crafters"], r["profit"]) == (["Tailor Guy"], 200)  # priced by that realm's scan

    res = client.put("/api/selection", json={"realm": "Nowhere", "faction": "Horde"})
    assert res.status_code == 400


def test_sources_and_sync_now(client: TestClient, conn: Connection, wow_root: Path) -> None:
    assert client.get("/api/status").json()["characters"] == 4
    missing = client.put("/api/sources", json={"altarmy_path": str(wow_root / "missing.lua")})
    assert missing.status_code == 404

    other = wow_root / "AltArmy_TBC.lua"
    other.write_bytes(ALTARMY_SV.replace(b'["Newbie"]', b'["Newbie Two"]'))
    status = client.put("/api/sources", json={"altarmy_path": str(other)}).json()
    assert status["altarmy_path"] == str(other)
    assert status["data_version"] == 2
    assert "Newbie Two" in [c.name for c in store.load_characters(conn, ME, FOREVER)]

    assert client.post("/api/sync").json()["data_version"] == 3  # forced, even though nothing changed

    (wow_root / SV_DIR / "Auctionator.lua").write_bytes(_saved_variables({"Atiesh": {"1": _entry(1)}}))
    warnings = client.post("/api/sync").json()["warnings"]
    assert warnings == ["Auctionator has no prices for Dreamscythe (Horde). Scan that auction house in game."]


def test_altarmy_files(client: TestClient, conn: Connection, wow_root: Path) -> None:
    found = str(wow_root / SV_DIR / "AltArmy_TBC.lua")
    assert client.get("/api/altarmy/files").json() == {"files": [found], "default": found}
    users.update_sync(conn, ME, FOREVER, altarmy_path=r"C:\elsewhere\AltArmy_TBC.lua")
    assert client.get("/api/altarmy/files").json()["default"] == r"C:\elsewhere\AltArmy_TBC.lua"


def test_reload_rereads_database(client: TestClient, priced: Connection) -> None:
    def profit() -> int:
        (r,) = client.get("/api/rank").json()["results"]
        return int(r["profit"])

    assert profit() == 200
    set_prices(priced, {2: 50})
    assert profit() == 200  # cached
    assert client.post("/api/reload").json()["prices"] == 2
    assert profit() == 250


def test_serves_built_frontend(
    tmp_path: Path, game_versions: dict[str, GameVersion], database: db.Database
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>altarmy-profit</html>")
    client = TestClient(create_app(game_versions, database=database, static_dir=dist, wow_roots=()))
    assert "altarmy-profit" in client.get("/").text
    assert client.get("/api/status", params={"game_version": "tbc"}).json()["recipes"] == 0


def test_missing_frontend_build_gives_hint(client: TestClient) -> None:
    res = client.get("/")
    assert res.status_code == 200
    assert "npm run build" in res.json()["detail"]


def test_routes_need_a_known_game_version(client: TestClient) -> None:
    client.params = client.params.remove("game_version")
    assert client.get("/api/status").status_code == 422
    assert client.get("/api/status", params={"game_version": "retail"}).status_code == 422


def test_each_game_version_has_its_own_data(
    client: TestClient, priced: Connection, tmp_path: Path, wow_root: Path
) -> None:
    assert len(client.get("/api/rank").json()["results"]) == 1  # Forever: the tailor's robe
    client.put("/api/ah-blocked/3")
    tbc = {"game_version": "tbc"}
    status = client.get("/api/status", params=tbc).json()
    assert (status["recipes"], status["prices"], status["characters"]) == (0, 0, 0)
    assert client.get("/api/ah-blocked", params=tbc).json()["items"] == []
    assert client.get("/api/rank", params=tbc).json()["results"] == []
    assert client.get("/api/altarmy/files", params=tbc).json() == {"files": [], "default": None}
    assert client.get("/api/versions").json() == [
        {"key": "forever", "label": "WoW: Forever", "build": None, "recipes": 1},
        {"key": "tbc", "label": "TBC Anniversary", "build": None, "recipes": 0},
    ]


def test_update_game_data_uses_the_versions_product(
    client: TestClient, db2_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[str] = []

    def latest(product: str) -> str:
        asked.append(product)
        return "2.5.6.1"

    monkeypatch.setattr(ingest, "latest_build", latest)
    monkeypatch.setattr(ingest, "download_all", lambda build, cache_dir: db2_paths)
    res = client.post("/api/game-data/update", params={"game_version": "tbc"}).json()
    assert asked == ["wow_anniversary"]
    assert (res["build"], res["vendor_items"]) == ("2.5.6.1", 0)  # TBC's data dir has no vendor list here
    assert client.get("/api/status").json()["build"] is None  # Forever untouched


# --- users, tiers and prices ------------------------------------------------------------------------
FREE = {"Authorization": "Bearer anonymous:guest"}
LINKED = {"Authorization": "Bearer google.com:g1"}


@pytest.fixture
def hosted(tmp_path: Path, game_versions: dict[str, GameVersion], database: db.Database) -> TestClient:
    """Hosted mode, with fake tokens (see `FakeVerifier`): FREE is an anonymous user, LINKED a Google one.
    Local mode would sync addon files from the WoW install the `wow_root` fixture makes."""
    app = create_app(
        game_versions,
        database=database,
        cache_dir=tmp_path / "cache",
        static_dir=tmp_path / "nodist",
        wow_roots=[tmp_path / "World of Warcraft"],
        mode="hosted",
        verifier=FakeVerifier(),
        firebase=auth.FirebaseConfig("demo-altarmy", "key", "demo-altarmy.firebaseapp.com", "127.0.0.1:9099"),
    )
    c = TestClient(app)
    c.params = c.params.set("game_version", "forever")
    return c


def test_local_mode_needs_no_sign_in(client: TestClient) -> None:
    assert client.get("/api/me").json() == {"uid": "local", "tier": "linked", "free_max_level": 30}
    assert client.get("/api/me", headers=FREE).json()["uid"] == "local"  # tokens are ignored
    assert client.get("/api/config").json() == {"mode": "local", "firebase": None}


def test_hosted_mode_signs_users_in(hosted: TestClient, conn: Connection) -> None:
    assert hosted.get("/api/config").json() == {
        "mode": "hosted",
        "firebase": {
            "api_key": "key",
            "auth_domain": "demo-altarmy.firebaseapp.com",
            "project_id": "demo-altarmy",
            "emulator_url": "http://127.0.0.1:9099",
        },
    }
    assert hosted.get("/api/versions").status_code == 200  # public
    assert hosted.get("/api/me").status_code == 401
    assert hosted.get("/api/me", headers={"Authorization": "Bearer nonsense"}).status_code == 401
    assert hosted.get("/api/me", headers=FREE).json() == {
        "uid": "guest",
        "tier": "free",
        "free_max_level": 30,
    }
    assert hosted.get("/api/me", headers=LINKED).json()["tier"] == "linked"
    u = schema.users
    rows = conn.execute(select(u.c.uid, u.c.tier).order_by(u.c.uid)).all()
    assert [tuple(r) for r in rows] == [("g1", "linked"), ("guest", "free"), ("local", "linked")]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/characters"),
        ("PUT", "/api/selection"),
        ("GET", "/api/rank"),
        ("POST", "/api/evaluate"),
        ("GET", "/api/ah-blocked"),
        ("PUT", "/api/ah-blocked/1"),
        ("DELETE", "/api/ah-blocked/1"),
    ],
)
def test_free_users_get_403_from_linked_routes(hosted: TestClient, method: str, path: str) -> None:
    body = {"realm": "R", "faction": "Horde"} if path == "/api/selection" else {"recipe_id": 1, "choices": {}}
    res = hosted.request(method, path, headers=FREE, json=body if method in ("PUT", "POST") else None)
    assert res.status_code == 403
    assert "Link your account" in res.json()["detail"]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/sync"),
        ("PUT", "/api/sources"),
        ("GET", "/api/auctionator/files"),
        ("GET", "/api/altarmy/files"),
        ("POST", "/api/game-data/update"),
        ("POST", "/api/reload"),
    ],
)
def test_local_file_and_admin_routes_are_gone_in_hosted_mode(
    hosted: TestClient, method: str, path: str
) -> None:
    res = hosted.request(method, path, headers=LINKED, json={} if method == "PUT" else None)
    assert res.status_code == 404


def test_hosted_status_never_syncs_local_files(hosted: TestClient, conn: Connection, wow_root: Path) -> None:
    status = hosted.get("/api/status", headers=LINKED).json()
    assert (status["characters"], status["warnings"], status["db_path"]) == (0, [], "")
    assert hosted.get("/api/characters", headers=LINKED).json()["groups"] == []
    assert store.count_characters(conn, ME, FOREVER) == 0  # nor for the local user


def test_linked_users_rank_their_own_characters(hosted: TestClient, priced: Connection) -> None:
    assert hosted.get("/api/rank", headers=LINKED).json()["total"] == 0  # the tailor is the local user's
    store.save_characters(priced, "g1", FOREVER, altarmy.parse_characters(ALTARMY_SV))
    selection = {"realm": "Classic Beta PvE", "faction": "Horde"}
    assert hosted.put("/api/selection", headers=LINKED, json=selection).json()["selection"] == selection
    assert hosted.get("/api/rank", headers=LINKED).json()["total"] == 1
    hosted.put("/api/ah-blocked/3", headers=LINKED)
    assert store.load_ah_blocked(priced, ME, FOREVER) == []


def gated(conn: Connection) -> int:
    """Linen (level 0), thread (0) and the robe, raised to level 40, priced on Classic Beta PvE."""
    i = schema.items
    conn.execute(i.update().where(i.c.game_version == FOREVER, i.c.id == 3).values(required_level=40))
    return set_prices(conn, {1: 20, 2: 100, 3: 999})


def test_realms_list_auction_houses(client: TestClient, priced: Connection) -> None:
    set_prices(priced, {1: 7}, realm="Dreamscythe", faction="Horde")
    pve, dream = client.get("/api/realms").json()
    assert (pve["realm"], pve["faction"], pve["prices"]) == ("Classic Beta PvE", "", 2)
    assert (dream["realm"], dream["faction"], dream["prices"]) == ("Dreamscythe", "Horde", 1)
    assert dream["last_scan"] is not None
    assert client.get("/api/realms", params={"game_version": "tbc"}).json() == []


def test_prices_search_by_name(client: TestClient, db2_paths: dict[str, Path], conn: Connection) -> None:
    ingest.build_db(db2_paths, conn, FOREVER)
    ah = gated(conn)
    body = client.get("/api/prices", params={"auction_house_id": ah}).json()
    assert [(i["name"], i["ah_price"]) for i in body["items"]] == [
        ("Coarse Thread", 100),
        ("Green Robe", 999),
        ("Linen Cloth", 20),
    ]
    assert (body["total"], body["gated"]) == (3, False)
    body = client.get("/api/prices", params={"auction_house_id": ah, "q": "LINEN", "top": 1}).json()
    assert ([i["id"] for i in body["items"]], body["total"]) == ([1], 1)
    body = client.get("/api/prices", params={"auction_house_id": ah, "q": "e", "top": 1}).json()
    assert (len(body["items"]), body["total"]) == (1, 3)
    assert client.get("/api/prices", params={"auction_house_id": ah, "q": "%"}).json()["total"] == 0
    tbc: dict[str, str | int] = {"auction_house_id": ah, "game_version": "tbc"}
    assert client.get("/api/prices", params=tbc).status_code == 404  # a Forever auction house


def test_free_users_see_prices_up_to_level_30(
    hosted: TestClient, db2_paths: dict[str, Path], conn: Connection
) -> None:
    ingest.build_db(db2_paths, conn, FOREVER)
    params = {"auction_house_id": gated(conn)}
    free = hosted.get("/api/prices", params=params, headers=FREE).json()
    assert [i["name"] for i in free["items"]] == ["Coarse Thread", "Linen Cloth"]
    assert (free["total"], free["gated"]) == (2, True)
    linked = hosted.get("/api/prices", params=params, headers=LINKED).json()
    assert (linked["total"], linked["gated"]) == (3, False)

    assert hosted.get("/api/prices/3", params=params, headers=FREE).status_code == 403
    assert hosted.get("/api/prices/1", params=params, headers=FREE).json()["item"]["ah_price"] == 20
    history = hosted.get("/api/prices/3", params=params, headers=LINKED).json()
    assert (history["item"]["name"], history["days"]) == ("Green Robe", [])
    assert hosted.get("/api/prices/99", params=params, headers=LINKED).status_code == 404


def test_price_history_newest_first(
    client: TestClient, db2_paths: dict[str, Path], conn: Connection, wow_root: Path
) -> None:
    ingest.build_db(db2_paths, conn, FOREVER)
    with_tailor(conn)
    ah = client.get("/api/status").json()["auction_house_id"]  # synced Classic Beta PvE's scan
    assert ah is not None
    days = client.get("/api/prices/1", params={"auction_house_id": ah}).json()["days"]
    assert days and days[0]["low"] == 20
    assert [d["day"] for d in days] == sorted((d["day"] for d in days), reverse=True)
