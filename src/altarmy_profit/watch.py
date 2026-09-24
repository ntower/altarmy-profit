"""The CLI watcher (`altarmy-profit watch`): uploads the Alt Army and Auctionator SavedVariables files to a
server whenever WoW rewrites them (on logout or /reload).

It needs no database: which files it has sent is a small JSON state file of {path: mtime}. The WoW
flavor folder a file is in (`_anniversary_`, `_classic_beta_`) says its game version. Files go gzipped to
`POST /api/uploads`, Alt Army first so the server names new auction houses after the characters' realms.
Only standard library HTTP (urllib), so the CLI needs no extra packages.
"""

from __future__ import annotations

import gzip
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from . import prices, versions

DEFAULT_STATE = Path.home() / ".altarmy-profit" / "watch-state.json"
KINDS = (("altarmy", prices.find_altarmy_files), ("auctionator", prices.find_auctionator_files))
MAX_BACKOFF = 300  # seconds between retries after failures, at most

# (url, headers, body) -> (HTTP status, response body); `urllib_transport` or a test double
Transport = Callable[[str, Mapping[str, str], bytes], tuple[int, bytes]]
Log = Callable[[str], None]


class UploadFailed(Exception):
    """The server could not be reached or failed (5xx, 429): try again later."""


class BadKey(Exception):
    """The server refused the API key: stop."""


@dataclass(frozen=True)
class Found:
    path: Path
    game_version: str
    kind: str  # altarmy | auctionator
    mtime_ns: int


def version_of(path: Path) -> str | None:
    """The game version whose flavor folder `path` is in."""
    parts = {p.lower() for p in path.parts}
    for v in versions.VERSIONS.values():
        if any(f.lower() in parts for f in v.flavor_folders):
            return v.key
    return None


def find_files(roots: Iterable[Path] = prices.WOW_ROOTS) -> list[Found]:
    """Both addons' files for every game version under the WoW installs: Alt Army files first, then by
    game version."""
    order = list(versions.VERSIONS)
    out = []
    roots = list(roots)
    for kind, find in KINDS:
        found = []
        for path in find(roots, None):
            gv = version_of(path)
            if gv is not None:
                found.append(Found(path, gv, kind, path.stat().st_mtime_ns))
        out += sorted(found, key=lambda f: (order.index(f.game_version), str(f.path)))
    return out


def changed(found: Iterable[Found], state: Mapping[str, int]) -> list[Found]:
    """The files whose modified time is not the one last sent."""
    return [f for f in found if state.get(str(f.path)) != f.mtime_ns]


def load_state(path: Path) -> dict[str, int]:
    """{file: mtime_ns last sent}; empty if missing or unreadable (everything is sent again)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): int(v) for k, v in data.items()} if isinstance(data, dict) else {}


def save_state(path: Path, state: Mapping[str, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(dict(state), indent=1), encoding="utf-8")
    tmp.replace(path)


def multipart_body(fields: Mapping[str, str], filename: str, data: bytes) -> tuple[str, bytes]:
    """(Content-Type, body) of a multipart/form-data request with `fields` and one `file`."""
    boundary = "altarmy-" + secrets.token_hex(16)
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        for name, value in fields.items()
    ]
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n".encode()
        + data
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return f"multipart/form-data; boundary={boundary}", b"".join(parts)


def urllib_transport(url: str, headers: Mapping[str, str], body: bytes) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
    try:
        with urllib.request.urlopen(request, timeout=120) as res:
            return int(res.status), bytes(res.read())
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def upload(server: str, key: str | None, f: Found, transport: Transport) -> tuple[bool, str]:
    """Send one file. Returns (accepted, the server's summary or complaint); raises BadKey on 401/403 and
    UploadFailed when it should be retried."""
    fields = {"kind": f.kind, "via": "watcher", "modified_at": str(f.mtime_ns // 10**6)}
    content_type, body = multipart_body(fields, f.path.name, gzip.compress(f.path.read_bytes()))
    headers = {"Content-Type": content_type, "User-Agent": "altarmy-profit-watch"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    query = urllib.parse.urlencode({"game_version": f.game_version})
    url = f"{server.rstrip('/')}/api/uploads?{query}"
    try:
        status, text = transport(url, headers, body)
    except (OSError, urllib.error.URLError) as e:
        raise UploadFailed(f"could not reach {server}: {e}") from e
    detail = _detail(text)
    if status in (401, 403):
        raise BadKey(f"the server refused the key ({status}): {detail}")
    if status == 429 or status >= 500:
        raise UploadFailed(f"{status}: {detail}")
    return status == 200, detail


def _detail(text: bytes) -> str:
    try:
        body = json.loads(text)
    except ValueError:
        return text[:200].decode("utf-8", "replace")
    return str(body.get("detail", "")) if isinstance(body, dict) else ""


def sync_once(
    roots: Iterable[Path],
    server: str,
    key: str | None,
    state_path: Path,
    transport: Transport = urllib_transport,
    log: Log = print,
) -> list[Found]:
    """Upload every file changed since last time; returns them. A file the server refuses (4xx) is logged
    and skipped until WoW rewrites it; a failure (UploadFailed) leaves it to be retried."""
    state = load_state(state_path)
    sent = []
    for f in changed(find_files(roots), state):
        accepted, detail = upload(server, key, f, transport)
        log(f"{'Uploaded' if accepted else 'Rejected'} {f.game_version} {f.path.name}: {detail}")
        state[str(f.path)] = f.mtime_ns
        save_state(state_path, state)
        sent.append(f)
    return sent


def run(
    roots: Iterable[Path],
    server: str,
    key: str | None,
    state_path: Path = DEFAULT_STATE,
    interval: float = 15,
    transport: Transport = urllib_transport,
    log: Log = print,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Watch forever: check every `interval` seconds, backing off after failures. Returns on BadKey."""
    roots = list(roots)
    failures = 0
    while True:
        try:
            sync_once(roots, server, key, state_path, transport, log)
            failures = 0
        except UploadFailed as e:
            failures += 1
            log(f"Upload failed ({e}); retrying.")
        except BadKey as e:
            log(f"Stopped: {e}. Make a new key on the site's Manage tab.")
            return
        sleep(min(interval * 2**failures, MAX_BACKOFF))
