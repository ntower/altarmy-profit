"""The CLI watcher: finds the addon files, notices rewrites, uploads them to the server."""

import gzip
import os
from collections.abc import Mapping
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection

from altarmy_profit import cli, prices, store, watch
from altarmy_profit.versions import VERSIONS

from .conftest import FOREVER, ME, SV_DIR
from .test_altarmy import ALTARMY_SV
from .test_api import client  # noqa: F401  (fixture)
from .test_auctionator import _entry, _saved_variables


def touch(path: Path) -> None:
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))


@pytest.fixture
def tbc_files(wow_root: Path) -> Path:
    """TBC's copies of both files, next to the `wow_root` fixture's Forever ones."""
    sv = wow_root / SV_DIR.replace("_classic_beta_", "_anniversary_")
    sv.mkdir(parents=True)
    (sv / "AltArmy_TBC.lua").write_bytes(ALTARMY_SV)
    (sv / "Auctionator.lua").write_bytes(_saved_variables({"Dreamscythe Horde": {"1": _entry(5)}}))
    return sv


def test_finds_both_versions_files_characters_first(wow_root: Path, tbc_files: Path) -> None:
    found = watch.find_files([wow_root])
    assert [(f.game_version, f.kind, f.path.parent.parts[-5]) for f in found] == [
        ("forever", "altarmy", "_classic_beta_"),
        ("tbc", "altarmy", "_anniversary_"),
        ("forever", "auctionator", "_classic_beta_"),
        ("tbc", "auctionator", "_anniversary_"),
    ]


def test_version_of_a_path() -> None:
    assert watch.version_of(Path(r"C:\WoW\_anniversary_\WTF\Account\A\SavedVariables\x.lua")) == "tbc"
    assert watch.version_of(Path(r"C:\WoW\_classic_beta_\WTF\x.lua")) == "forever"
    assert watch.version_of(Path(r"C:\WoW\_retail_\WTF\x.lua")) is None


def test_changed_and_state_file(wow_root: Path, tmp_path: Path) -> None:
    state_path = tmp_path / "state" / "watch.json"
    state = watch.load_state(state_path)
    assert state == {}
    found = watch.find_files([wow_root])
    assert watch.changed(found, state) == found
    for f in found:
        state[str(f.path)] = f.mtime_ns
    watch.save_state(state_path, state)
    assert watch.load_state(state_path) == state
    touch(wow_root / SV_DIR / "Auctionator.lua")
    (again,) = watch.changed(watch.find_files([wow_root]), state)
    assert again.kind == "auctionator"
    state_path.write_text("not json")
    assert watch.load_state(state_path) == {}  # a broken state file means upload everything again


def test_multipart_body_round_trips() -> None:
    content_type, body = watch.multipart_body({"kind": "altarmy"}, "AltArmy_TBC.lua", b"\x00data\r\n--x")
    assert content_type.startswith("multipart/form-data; boundary=")
    boundary = content_type.split("boundary=")[1].encode()
    assert body.count(b"--" + boundary) == 3
    assert b'name="kind"\r\n\r\naltarmy\r\n' in body
    assert b'filename="AltArmy_TBC.lua"' in body and b"\x00data\r\n--x" in body


class Server:
    """A transport that hands the watcher's requests to the API's TestClient."""

    def __init__(self, api: TestClient | None, status: int | None = None) -> None:
        self.client = api
        self.status = status
        self.seen: list[tuple[str, Mapping[str, str]]] = []

    def __call__(self, url: str, headers: Mapping[str, str], body: bytes) -> tuple[int, bytes]:
        self.seen.append((url, headers))
        if self.client is None:
            return self.status or 500, b'{"detail": "no"}'
        res = self.client.post(url.removeprefix("http://server"), headers=dict(headers), content=body)
        return res.status_code, res.content


def test_sync_uploads_what_changed(
    client: TestClient,  # noqa: F811
    conn: Connection,
    wow_root: Path,
    tmp_path: Path,
) -> None:
    server = Server(client)
    state = tmp_path / "watch.json"
    sent = watch.sync_once([wow_root], "http://server/", None, state, server, print)
    assert [(f.game_version, f.kind) for f in sent] == [("forever", "altarmy"), ("forever", "auctionator")]
    assert server.seen[0][0] == "http://server/api/uploads?game_version=forever"
    assert "Authorization" not in server.seen[0][1]  # no key given (a local server)
    assert store.count_characters(conn, ME, FOREVER) == 4
    assert prices.find_auction_house(conn, FOREVER, "Classic Beta PvE", "") is not None

    assert watch.sync_once([wow_root], "http://server", None, state, server, print) == []
    touch(wow_root / SV_DIR / "AltArmy_TBC.lua")
    (again,) = watch.sync_once([wow_root], "http://server", "ak_k", state, server, print)
    assert again.kind == "altarmy"
    assert server.seen[-1][1]["Authorization"] == "Bearer ak_k"


def test_sync_sends_gzip_and_the_modified_time(wow_root: Path, tmp_path: Path) -> None:
    got: list[bytes] = []

    def capture(url: str, headers: Mapping[str, str], body: bytes) -> tuple[int, bytes]:
        got.append(body)
        return 200, b"{}"

    watch.sync_once([wow_root], "http://s", "ak_k", tmp_path / "s.json", capture, print)
    body = got[0]
    assert b'name="via"\r\n\r\nwatcher' in body
    mtime_ms = (wow_root / SV_DIR / "AltArmy_TBC.lua").stat().st_mtime_ns // 10**6
    assert f'name="modified_at"\r\n\r\n{mtime_ms}\r\n'.encode() in body
    start = body.index(b"\x1f\x8b")
    assert gzip.decompress(body[start : body.index(b"\r\n--", start)]) == ALTARMY_SV


def test_failed_uploads_are_retried_and_a_bad_key_stops(wow_root: Path, tmp_path: Path) -> None:
    state = tmp_path / "s.json"
    with pytest.raises(watch.UploadFailed, match="500"):
        watch.sync_once([wow_root], "http://s", "ak_k", state, Server(None, 500), print)
    assert watch.load_state(state) == {}  # nothing recorded: the next round tries again
    with pytest.raises(watch.BadKey):
        watch.sync_once([wow_root], "http://s", "ak_k", state, Server(None, 401), print)
    rejected = watch.sync_once([wow_root], "http://s", "ak_k", state, Server(None, 400), print)
    assert len(rejected) == 2  # a file the server refuses is skipped until WoW rewrites it
    assert len(watch.load_state(state)) == 2


def test_every_version_has_a_flavor() -> None:
    assert all(v.flavor_folders for v in VERSIONS.values())


def test_cli_watch_once(wow_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str | None]] = []

    def fake_sync(roots: list[Path], server: str, key: str | None, state: Path) -> list[watch.Found]:
        calls.append((server, key))
        return []

    monkeypatch.setattr(watch, "sync_once", fake_sync)
    monkeypatch.setenv("ALTARMY_KEY", "ak_env")
    args = [
        "watch",
        "--server",
        "http://s",
        "--once",
        "--wow-root",
        str(wow_root),
        "--state",
        str(tmp_path / "s"),
    ]
    cli.main(args)
    assert calls == [("http://s", "ak_env")]
    assert not (tmp_path / "data").exists()  # no database touched
    with pytest.raises(SystemExit, match="No Alt Army"):
        cli.main(["watch", "--server", "http://s", "--once", "--wow-root", str(tmp_path / "none")])


def test_run_backs_off_and_stops_on_a_bad_key(wow_root: Path, tmp_path: Path) -> None:
    statuses = iter([503, 503, 401])
    naps: list[float] = []
    logged: list[str] = []

    def flaky(url: str, headers: Mapping[str, str], body: bytes) -> tuple[int, bytes]:
        return next(statuses), b'{"detail": "busy"}'

    watch.run([wow_root], "http://s", "ak_k", tmp_path / "s.json", 10, flaky, logged.append, naps.append)
    assert naps == [20, 40]  # doubled after each failure
    assert logged[-1].startswith("Stopped: the server refused the key (401)")
