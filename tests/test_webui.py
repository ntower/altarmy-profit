import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest  # noqa: E402

from wowprofit import ingest, prices, webui  # noqa: E402
from wowprofit.engine import Item, Recipe, Result  # noqa: E402

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


def run_app(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    monkeypatch.setenv(webui.DB_ENV, str(db_path))
    webui.load_base_market.clear()
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
    assert at.sidebar.multiselect[0].options == ["Tailoring"]

    at.sidebar.multiselect[0].select("Tailoring").run()
    assert not at.exception
    df = at.dataframe[0].value
    assert list(df["Recipe"]) == ["Green Robe"]
    assert list(df["Profit"]) == ["0g 02s 00c"]


def test_app_reports_empty_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    at = run_app(tmp_path / "empty.db", monkeypatch)
    assert not at.exception
    assert "wowprofit ingest" in at.error[0].value
