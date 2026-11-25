"""Who is calling: every API request carries `Authorization: Bearer <token>`.

- Firebase ID tokens (the frontend signs in with Google through Firebase
  Auth) are checked against Google's published keys, for this project.
- With CANVAS_DEV_AUTH=1 (local work and tests only), "dev:<email>" is
  accepted as that user, no password.

Then the email must be on the allowlist (CANVAS_ALLOWED_EMAILS).
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass

import jwt

from .config import Settings
from .contract import ErrorCode
from .errors import ApiError

# Firebase's token-signing keys, as a JWK set.
FIREBASE_KEYS_URL = (
    "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com"
)


@dataclass(frozen=True)
class User:
    id: str
    email: str


def is_admin(settings: Settings, email: str) -> bool:
    """An admin: on the allowlist (CANVAS_ALLOWED_EMAILS), or anyone in local
    work (CANVAS_DEV_AUTH). Admins may lift a collection's daily limits."""
    return settings.dev_auth or email.lower() in settings.allowed_emails


def _unauthenticated(message: str = "sign in first") -> ApiError:
    return ApiError(401, ErrorCode.unauthenticated, message)


class Authenticator:
    def __init__(self, settings: Settings) -> None:
        self._project = settings.firebase_project_id
        self._dev = settings.dev_auth
        self._allowed = settings.allowed_emails
        self._keys = (
            jwt.PyJWKClient(FIREBASE_KEYS_URL, cache_keys=True, lifespan=3600)
            if self._project
            else None
        )

    def user(self, authorization: str | None) -> User:
        """The signed-in user, or 401/403. Blocking (may fetch keys)."""
        if not authorization or not authorization.lower().startswith("bearer "):
            raise _unauthenticated()
        token = authorization[7:].strip()
        if self._dev and token.startswith("dev:"):
            email = token[4:].strip().lower()
            if "@" not in email:
                raise _unauthenticated("a dev token is dev:<email>")
            digest = hashlib.sha256(email.encode()).hexdigest()[:20]
            user = User(id=f"dev-{digest}", email=email)
            if self._allowed and email not in self._allowed:
                raise self._not_allowed(email)
            return user
        if self._keys is None:
            raise _unauthenticated()
        user = self._firebase_user(token)
        if user.email not in self._allowed:
            raise self._not_allowed(user.email)
        return user

    def _firebase_user(self, token: str) -> User:
        try:
            key = self._keys.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                audience=self._project,
                issuer=f"https://securetoken.google.com/{self._project}",
                options={"require": ["exp", "iat", "sub", "aud", "iss"]},
                leeway=10,
            )
        except jwt.PyJWTError as exc:
            raise _unauthenticated("your sign-in expired or is invalid; sign in again") from exc
        if claims.get("auth_time", 0) > time.time() + 10 or not claims.get("sub"):
            raise _unauthenticated()
        email = str(claims.get("email") or "").lower()
        if not email or not claims.get("email_verified"):
            raise ApiError(403, ErrorCode.forbidden, "your account has no verified email")
        return User(id=claims["sub"], email=email)

    @staticmethod
    def _not_allowed(email: str) -> ApiError:
        return ApiError(
            403,
            ErrorCode.forbidden,
            f"{email} doesn't have access to this app yet",
            {"email": email},
        )
