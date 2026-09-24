import sqlite3
import urllib.error
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wowprofit import db, ingest, prices
from wowprofit.api import create_app

from .test_auctionator import _entry, _saved_variables


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    app = create_app(tmp_path / "test.db", cache_dir=tmp_path / "cache", static_dir=tmp_path / "nodist")
    return TestClient(app)


@pytest.fixture
def priced(db2_paths: dict[str, Path], conn: sqlite3.Connection) -> sqlite3.Connection:
    """The conftest DB (same file as the client's) with game data and prices linen=20, thread=100."""
    ingest.build_db(db2_paths, conn)
    prices.set_price(conn, 1, 20)
    prices.set_price(conn, 2, 100)
    conn.commit()
    return conn


def test_empty_db(client: TestClient) -> None:
    status = client.get("/api/status").json()
    assert status["recipes"] == 0
    assert status["build"] is None
    assert status["last_auctionator_import"] is None
    assert status["db_path"].endswith("test.db")
    assert client.get("/api/professions").json() == []


def test_rank_selected_profession(client: TestClient, priced: sqlite3.Connection) -> None:
    assert client.get("/api/professions").json() == ["Tailoring"]
    (r,) = client.get("/api/rank", params={"professions": ["Tailoring"]}).json()["results"]
    assert r["recipe"] == "Green Robe"
    assert r["profession"] == "Tailoring"
    assert (r["output_name"], r["output_count"]) == ("Green Robe", 1)
    assert (r["cost"], r["revenue"], r["profit"]) == (300, 500, 200)
    assert r["roi"] == pytest.approx(2 / 3)
    assert r["best_exit"] == "vendor"
    assert r["chain"] == []
    assert {"kind": "vendor", "value": 500} in r["exits"]


def test_rank_filters_and_validation(client: TestClient, priced: sqlite3.Connection) -> None:
    high = client.get("/api/rank", params={"professions": ["Tailoring"], "min_profit": 201})
    assert high.json()["results"] == []
    assert client.get("/api/rank", params={"professions": ["Alchemy"]}).json()["results"] == []
    assert client.get("/api/rank").json()["results"] == []
    assert client.get("/api/rank", params={"professions": ["Tailoring"], "top": 501}).status_code == 422


def test_update_game_data_invalidates_cache(
    client: TestClient, db2_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ingest, "latest_build", lambda: "9.9.9.1")
    monkeypatch.setattr(ingest, "download_all", lambda build, cache_dir: db2_paths)
    assert client.get("/api/professions").json() == []  # prime the cache

    res = client.post("/api/game-data/update")
    assert res.status_code == 200
    assert res.json()["build"] == "9.9.9.1"
    assert res.json()["items"] == 3
    assert client.get("/api/status").json()["build"] == "9.9.9.1"
    assert client.get("/api/professions").json() == ["Tailoring"]


def test_update_game_data_network_error(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail() -> str:
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(ingest, "latest_build", fail)
    res = client.post("/api/game-data/update")
    assert res.status_code == 502
    assert "offline" in res.json()["detail"]


def test_auctionator_files_default(
    client: TestClient, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = [Path(r"W\_classic_\A.lua"), Path(r"W\_classic_beta_\A.lua")]
    monkeypatch.setattr(prices, "find_auctionator_files", lambda: files)
    body = client.get("/api/auctionator/files").json()
    assert body == {"files": [str(f) for f in files], "default": str(files[1])}
    db.set_meta(conn, "auctionator_path", str(files[0]))
    assert client.get("/api/auctionator/files").json()["default"] == str(files[0])


def test_auctionator_realms_and_import(
    client: TestClient, db2_paths: dict[str, Path], conn: sqlite3.Connection, tmp_path: Path
) -> None:
    ingest.build_db(db2_paths, conn)
    sv = tmp_path / "Auctionator.lua"
    sv.write_bytes(_saved_variables({"A": {"1": _entry(1)}, "B": {"1": _entry(20), "2": _entry(100)}}))

    realms = client.get("/api/auctionator/realms", params={"path": str(sv)}).json()
    assert realms == {"realms": ["A", "B"], "default": "A"}
    assert client.get("/api/rank", params={"professions": ["Tailoring"]}).json()["results"] == []

    res = client.post("/api/auctionator/import", json={"path": str(sv), "realm": "B"})
    assert res.status_code == 200
    assert res.json() == {"realm": "B", "imported": 2, "unknown": 0}
    assert prices.load_prices(conn) == {1: 20, 2: 100}
    assert db.get_meta(conn, "auctionator_realm") == "B"
    assert client.get("/api/auctionator/realms", params={"path": str(sv)}).json()["default"] == "B"
    assert client.get("/api/status").json()["last_auctionator_import"] is not None

    (r,) = client.get("/api/rank", params={"professions": ["Tailoring"]}).json()["results"]
    assert r["profit"] == 200


def test_auctionator_errors(client: TestClient, tmp_path: Path) -> None:
    missing = str(tmp_path / "missing.lua")
    assert client.get("/api/auctionator/realms", params={"path": missing}).status_code == 404
    res = client.post("/api/auctionator/import", json={"path": missing, "realm": "A"})
    assert res.status_code == 404

    garbage = tmp_path / "garbage.lua"
    garbage.write_text("not auctionator")
    assert client.get("/api/auctionator/realms", params={"path": str(garbage)}).status_code == 400

    sv = tmp_path / "Auctionator.lua"
    sv.write_bytes(_saved_variables({"A": {"1": _entry(1)}}))
    res = client.post("/api/auctionator/import", json={"path": str(sv), "realm": "Nope"})
    assert res.status_code == 400
    assert "Nope" in res.json()["detail"]


def test_reload_rereads_database(client: TestClient, priced: sqlite3.Connection) -> None:
    def profit() -> int:
        (r,) = client.get("/api/rank", params={"professions": ["Tailoring"]}).json()["results"]
        return int(r["profit"])

    assert profit() == 200
    prices.set_price(priced, 2, 50)
    priced.commit()
    assert profit() == 200  # cached
    assert client.post("/api/reload").json()["prices"] == 2
    assert profit() == 250


def test_serves_built_frontend(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>wow-profit</html>")
    client = TestClient(create_app(tmp_path / "test.db", static_dir=dist))
    assert "wow-profit" in client.get("/").text
    assert client.get("/api/status").json()["recipes"] == 0


def test_missing_frontend_build_gives_hint(client: TestClient) -> None:
    res = client.get("/")
    assert res.status_code == 200
    assert "npm run build" in res.json()["detail"]
