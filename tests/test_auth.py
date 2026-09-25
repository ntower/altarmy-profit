"""Users, tiers and per-user state: who a token says it is, and that users never see each other's state."""

from collections.abc import Mapping
from typing import Any

import pytest
from sqlalchemy import Connection, select

from altarmy_profit import auth, schema, service, store, users
from altarmy_profit.altarmy import Character
from altarmy_profit.auth import User

from .conftest import FOREVER, ME


def claims(uid: str, provider: str) -> dict[str, Any]:
    """Firebase ID token claims as firebase-admin returns them."""
    return {"uid": uid, "sub": uid, "firebase": {"sign_in_provider": provider}}


class FakeVerifier:
    """Tokens are "<provider>:<uid>", e.g. "anonymous:abc" or "google.com:abc"; anything else is invalid.
    Also the account admin: `deleted` lists the uids deleted, and `fail` makes deletion fail."""

    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.fail = False

    def delete_user(self, uid: str) -> None:
        if self.fail:
            raise auth.AccountError("Firebase is down")
        self.deleted.append(uid)

    def verify(self, token: str) -> Mapping[str, Any]:
        provider, sep, uid = token.partition(":")
        if not sep or not uid:
            raise auth.InvalidToken("not a fake token")
        return claims(uid, provider)


@pytest.mark.parametrize(
    ("provider", "tier"),
    [("anonymous", "free"), ("google.com", "linked"), ("password", "linked"), ("custom", "linked")],
)
def test_user_from_claims(provider: str, tier: str) -> None:
    assert auth.user_from_claims(claims("u1", provider)) == User("u1", tier)  # type: ignore[arg-type]


def test_user_from_claims_needs_a_uid() -> None:
    with pytest.raises(auth.InvalidToken):
        auth.user_from_claims({"firebase": {"sign_in_provider": "anonymous"}})
    assert auth.user_from_claims({"sub": "s", "firebase": {}}) == User("s", "linked")


def test_mode_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALTARMY_MODE", raising=False)
    assert auth.mode_from_env() == "local"
    monkeypatch.setenv("ALTARMY_MODE", "hosted")
    assert auth.mode_from_env() == "hosted"
    monkeypatch.setenv("ALTARMY_MODE", "cloud")
    with pytest.raises(ValueError, match="ALTARMY_MODE"):
        auth.mode_from_env()


def test_firebase_config_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "FIREBASE_PROJECT_ID",
        "FIREBASE_API_KEY",
        "FIREBASE_AUTH_DOMAIN",
        "FIREBASE_AUTH_EMULATOR_HOST",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError, match="FIREBASE_PROJECT_ID"):
        auth.FirebaseConfig.from_env()
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "demo-altarmy")
    monkeypatch.setenv("FIREBASE_AUTH_EMULATOR_HOST", "127.0.0.1:9099")
    assert auth.FirebaseConfig.from_env() == auth.FirebaseConfig(
        "demo-altarmy", "emulator", "demo-altarmy.firebaseapp.com", "127.0.0.1:9099"
    )


def test_ensure_user_creates_and_follows_the_tier(conn: Connection) -> None:
    u = schema.users

    def row() -> Any:
        return conn.execute(select(u.c.tier, u.c.linked_at, u.c.created_at).where(u.c.uid == "g1")).one()

    users.ensure_user(conn, User("g1", "free"))
    tier, linked_at, created_at = row()
    assert (tier, linked_at) == ("free", None)
    users.ensure_user(conn, User("g1", "free"))
    users.ensure_user(conn, User("g1", "linked"))
    tier, linked_at, again = row()
    assert tier == "linked"
    assert linked_at is not None and again == created_at


def test_user_state_is_per_user(conn: Connection) -> None:
    other = "someone-else"
    users.ensure_user(conn, User(other, "linked"))
    mine = [Character("Realm", "Mine", "Horde", "MAGE", 60, ())]
    theirs = [
        Character("Realm", "Mine", "Horde", "MAGE", 60, ()),
        Character("Realm", "Two", "Horde", "MAGE", 1, ()),
    ]
    store.save_characters(conn, ME, FOREVER, mine)
    store.save_characters(conn, other, FOREVER, theirs)  # the same name is fine for another user
    assert [c.name for c in store.load_characters(conn, ME, FOREVER)] == ["Mine"]
    assert store.count_characters(conn, other, FOREVER) == 2
    store.save_characters(conn, ME, FOREVER, [])  # replacing mine leaves theirs
    assert store.count_characters(conn, other, FOREVER) == 2

    service.select(conn, other, FOREVER, "Realm", "Horde")
    service.bump_data_version(conn, other, FOREVER)
    assert users.get_settings(conn, other, FOREVER) == users.UserSettings("Realm", "Horde", 1)
    assert users.get_settings(conn, ME, FOREVER) == users.UserSettings()
    assert users.get_settings(conn, other, "tbc") == users.UserSettings()

    store.set_ah_blocked(conn, other, FOREVER, 7, True)
    assert store.load_ah_blocked(conn, ME, FOREVER) == []
    assert [i for i, _ in store.load_ah_blocked(conn, other, FOREVER)] == [7]


def test_settings_and_sync_roundtrip(conn: Connection) -> None:
    assert users.get_sync(conn, ME, FOREVER) == users.LocalSync()
    users.update_sync(conn, ME, FOREVER, altarmy_path="a.lua", altarmy_mtime=10**18 + 7)
    users.update_sync(conn, ME, FOREVER, auctionator_realm="")
    got = users.get_sync(conn, ME, FOREVER)
    assert (got.altarmy_path, got.altarmy_mtime, got.auctionator_realm) == ("a.lua", 10**18 + 7, "")
    assert users.get_sync(conn, ME, "tbc") == users.LocalSync()
    assert users.update_settings(conn, ME, FOREVER, data_version=3).data_version == 3
