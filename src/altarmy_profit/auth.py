"""Who is asking, and what their tier lets them see. No database or HTTP here.

Hosted mode signs every visitor in with Firebase (anonymously at first); the front end sends the Firebase
ID token and a `TokenVerifier` turns it into claims. Linking a Google or email account keeps the uid and
moves the user from the free to the linked tier. Local mode has one fixed user with the linked tier.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

from .db import LOCAL_UID

Tier = Literal["free", "linked"]
Mode = Literal["local", "hosted"]
MODES: tuple[Mode, ...] = ("local", "hosted")

# The free tier sees prices only for items a character of this level or lower can use. Raw materials
# (cloth, ore, herbs) have a required level of 0, so they are all free.
FREE_TIER_MAX_LEVEL = 30


@dataclass(frozen=True)
class User:
    uid: str
    tier: Tier

    @property
    def linked(self) -> bool:
        return self.tier == "linked"


LOCAL_USER = User(LOCAL_UID, "linked")


class InvalidToken(Exception):
    """The ID token is missing, malformed, expired or not for this project."""


class TokenVerifier(Protocol):
    def verify(self, token: str) -> Mapping[str, Any]:
        """The token's claims; InvalidToken if it does not verify."""
        ...


class AccountError(Exception):
    """The sign-in provider could not delete the account."""


@runtime_checkable
class AccountAdmin(Protocol):
    def delete_user(self, uid: str) -> None:
        """Delete the sign-in account (already gone is fine); AccountError if that failed."""
        ...


def user_from_claims(claims: Mapping[str, Any]) -> User:
    """Linked unless the token came from an anonymous sign-in."""
    uid = claims.get("uid") or claims.get("sub")
    if not isinstance(uid, str) or not uid:
        raise InvalidToken("token has no uid")
    firebase = claims.get("firebase")
    provider = firebase.get("sign_in_provider") if isinstance(firebase, Mapping) else None
    return User(uid, "free" if provider == "anonymous" else "linked")


def mode_from_env() -> Mode:
    """`ALTARMY_MODE`: local (the default) or hosted."""
    mode = os.environ.get("ALTARMY_MODE") or "local"
    if mode not in MODES:
        raise ValueError(f"ALTARMY_MODE must be local or hosted, not {mode!r}")
    return "hosted" if mode == "hosted" else "local"


@dataclass(frozen=True)
class FirebaseConfig:
    """What the front end needs to sign in (public values), plus the emulator when developing."""

    project_id: str
    api_key: str
    auth_domain: str
    emulator_host: str | None  # host:port of the Firebase Auth emulator, e.g. 127.0.0.1:9099

    @classmethod
    def from_env(cls) -> FirebaseConfig:
        """`FIREBASE_PROJECT_ID` (required), `FIREBASE_API_KEY`, `FIREBASE_AUTH_DOMAIN` and the emulator's
        `FIREBASE_AUTH_EMULATOR_HOST`, which firebase-admin reads too."""
        project_id = os.environ.get("FIREBASE_PROJECT_ID")
        if not project_id:
            raise ValueError("Hosted mode needs FIREBASE_PROJECT_ID.")
        emulator = os.environ.get("FIREBASE_AUTH_EMULATOR_HOST") or None
        return cls(
            project_id=project_id,
            # the emulator accepts any API key
            api_key=os.environ.get("FIREBASE_API_KEY") or ("emulator" if emulator else ""),
            auth_domain=os.environ.get("FIREBASE_AUTH_DOMAIN") or f"{project_id}.firebaseapp.com",
            emulator_host=emulator,
        )


class FirebaseVerifier:
    """Verifies Firebase ID tokens with firebase-admin (the `hosted` extra), and deletes accounts. Verifying
    needs only the project id (the signing keys are Google's public certificates); deleting needs
    credentials with Firebase Auth admin rights (on Cloud Run, the service account's). With
    `FIREBASE_AUTH_EMULATOR_HOST` set, firebase-admin talks to the emulator instead."""

    def __init__(self, project_id: str) -> None:
        import firebase_admin

        name = f"altarmy-{project_id}"
        try:
            self._app = firebase_admin.get_app(name)
        except ValueError:
            self._app = firebase_admin.initialize_app(options={"projectId": project_id}, name=name)

    def verify(self, token: str) -> Mapping[str, Any]:
        from firebase_admin import auth

        try:
            claims: Mapping[str, Any] = auth.verify_id_token(token, app=self._app)
        except (ValueError, auth.InvalidIdTokenError, auth.ExpiredIdTokenError) as e:
            raise InvalidToken(str(e)) from e
        return claims

    def delete_user(self, uid: str) -> None:
        from firebase_admin import auth, exceptions

        try:
            auth.delete_user(uid, app=self._app)
        except auth.UserNotFoundError:
            pass
        except (ValueError, exceptions.FirebaseError) as e:
            raise AccountError(str(e)) from e
