import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest  # noqa: E402

from wowprofit import db, ingest, prices, webui  # noqa: E402
from wowprofit.engine import Item, Recipe, Result  # noqa: E402

from .test_auctionator import _entry, _saved_variables  # noqa: E402

APP = str(Path(webui.__file__))


def test_build_rows_formats_money() -> None:
    recipe = Recipe(10, "Green Robe", 3, 1, ((1, 10),), "Tailoring")
    items = {3: Item(3, "Green Robe")}
    (row,) = webui.build_rows([Result(recipe, 300, 500, "vendor")], items)
    assert row == {
        "Profit": "0g 02s 00c",
        "ROI": "67%",
        "Recipe": "Green Robe",
        "Profession": "Tailoring",
        "Output": "1x Green Robe",
        "Cost": "0g 03s 00c",
        "Revenue": "0g 05s 00c",
        "Sell via": "vendor",
    }


def run_app(
    db_path: Path, monkeypatch: pytest.MonkeyPatch, auctionator_files: tuple[Path, ...] = ()
) -> AppTest:
    monkeypatch.setenv(webui.DB_ENV, str(db_path))
    monkeypatch.setattr(prices, "find_auctionator_files", lambda: list(auctionator_files))
    webui.load_base_market.clear()
    webui.auctionator_realms.clear()
    at = AppTest.from_file(APP, default_timeout=30)
    return at.run()


def test_app_ranks_selected_profession(
    db2_paths: dict[str, Path], conn: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ingest.build_db(db2_paths, conn)
    prices.set_price(conn, 1, 20)
    prices.set_price(conn, 2, 100)
    conn.commit()

    at = run_app(tmp_path / "test.db", monkeypatch)
    assert not at.exception
    assert not at.dataframe  # nothing until a profession is picked
    assert at.multiselect[0].options == ["Tailoring"]

    at.multiselect[0].select("Tailoring").run()
    assert not at.exception
    df = at.dataframe[0].value
    assert list(df["Recipe"]) == ["Green Robe"]
    assert list(df["Profit"]) == ["0g 02s 00c"]


def test_app_reports_empty_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    at = run_app(tmp_path / "empty.db", monkeypatch)
    assert not at.exception
    assert "Manage tab" in at.error[0].value


def test_default_auctionator_path_prefers_last_then_forever() -> None:
    files = [r"W\_classic_\A.lua", r"W\_classic_beta_\A.lua"]
    assert webui.default_auctionator_path(files, None) == 1
    assert webui.default_auctionator_path(files, files[0]) == 0
    assert webui.default_auctionator_path(files[:1], None) == 0
    assert webui.default_auctionator_path([], None) is None


def test_manage_downloads_latest_game_data(
    db2_paths: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ingest, "latest_build", lambda: "9.9.9.1")
    monkeypatch.setattr(ingest, "download_all", lambda build, cache_dir: db2_paths)
    at = run_app(tmp_path / "test.db", monkeypatch)
    assert at.error  # empty db

    at.button(key="update_game_data").click().run()
    assert not at.exception
    assert "Loaded build 9.9.9.1" in at.success[0].value
    assert not at.error  # search tab picked up the new recipes on the same run
    assert at.multiselect[0].options == ["Tailoring"]


def test_manage_imports_auctionator_prices(
    db2_paths: dict[str, Path], conn: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ingest.build_db(db2_paths, conn)
    sv = tmp_path / "Auctionator.lua"
    sv.write_bytes(_saved_variables({"A": {"1": _entry(1)}, "B": {"1": _entry(20), "2": _entry(100)}}))

    at = run_app(tmp_path / "test.db", monkeypatch, (sv,))
    assert at.selectbox(key="realm").options == ["A", "B"]
    at.selectbox(key="realm").select("B").run()
    at.button(key="import_auctionator").click().run()
    assert not at.exception
    assert "Imported 2 prices from B" in at.success[0].value
    assert prices.load_prices(conn) == {1: 20, 2: 100}
    assert db.get_meta(conn, "auctionator_realm") == "B"

    at.multiselect[0].select("Tailoring").run()
    assert list(at.dataframe[0].value["Profit"]) == ["0g 02s 00c"]
