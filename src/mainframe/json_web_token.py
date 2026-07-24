import datetime as dt
import time
from dataclasses import dataclass
from functools import cache
from json import JSONDecodeError
from threading import Condition
from typing import Any, Self

import jwt

from mainframe.constants import cf_access_settings
from mainframe.custom_exceptions import (
    BadCredentialsException,
    UnableCredentialsException,
)


class CoalescingPyJWKClient(jwt.PyJWKClient):
    """Refresh stale signing keys without allowing a request-driven stampede."""

    _missing_key_limit = 128

    def __init__(
        self,
        uri: str,
        refresh_interval: float = 1.0,
        lifespan: float = 300.0,
    ) -> None:
        super().__init__(uri, lifespan=lifespan, timeout=5)
        self._refresh_interval = refresh_interval
        self._refresh_condition = Condition()
        self._refreshing = False
        self._refreshing_kid: str | None = None
        self._refresh_generation = 0
        self._last_refresh_error: tuple[bool, str] | None = None
        self._next_refresh_at = 0.0
        self._known_key_ids: frozenset[str] = frozenset()
        self._missing_kids: dict[str, None] = {}

    @staticmethod
    def _missing_key_error() -> jwt.exceptions.PyJWKClientError:
        return jwt.exceptions.PyJWKClientError("Unable to find a matching signing key")

    def _record_keys(self, signing_keys: list[jwt.PyJWK]) -> None:
        key_ids = frozenset(key.key_id for key in signing_keys if key.key_id is not None)
        if self._known_key_ids and key_ids != self._known_key_ids:
            self._missing_kids.clear()
        self._known_key_ids = key_ids

    def _record_missing_key(self, kid: str) -> None:
        if len(self._missing_kids) >= self._missing_key_limit:
            self._missing_kids.pop(next(iter(self._missing_kids)))
        self._missing_kids[kid] = None

    def _cached_signing_keys(self) -> tuple[list[jwt.PyJWK], bool]:
        jwk_set_cache = self.jwk_set_cache
        had_cached_jwks = jwk_set_cache is not None and jwk_set_cache.get() is not None
        signing_keys = self.get_signing_keys()
        self._record_keys(signing_keys)
        return signing_keys, had_cached_jwks

    def _wait_for_refresh(self, timeout: float | None = None) -> None:
        self._refresh_condition.wait(timeout)

    def _claim_refresh(self, kid: str) -> bool:
        target_generation = self._refresh_generation + 1
        if self._refreshing and self._refreshing_kid != kid:
            target_generation += 1

        while self._refresh_generation < target_generation:
            if self._refreshing:
                self._wait_for_refresh()
                continue

            refresh_delay = self._next_refresh_at - time.monotonic()
            if refresh_delay > 0:
                self._wait_for_refresh(refresh_delay)
                continue

            self._refreshing = True
            self._refreshing_kid = kid
            return True

        return False

    def _refresh_signing_keys(
        self,
    ) -> tuple[list[jwt.PyJWK], jwt.exceptions.PyJWKClientError | None]:
        jwk_set_cache = self.jwk_set_cache
        cached_jwk_set = jwk_set_cache.get() if jwk_set_cache is not None else None
        signing_keys: list[jwt.PyJWK] = []
        refresh_error: jwt.exceptions.PyJWKClientError | None = None
        try:
            signing_keys = self.get_signing_keys(refresh=True)
        except (jwt.exceptions.PyJWTError, JSONDecodeError) as err:
            if isinstance(err, JSONDecodeError):
                refresh_error = jwt.exceptions.PyJWKClientConnectionError("The JWKS endpoint returned invalid JSON")
            elif isinstance(err, jwt.exceptions.PyJWKClientError):
                refresh_error = err
            else:
                refresh_error = jwt.exceptions.PyJWKClientError(str(err))
            if jwk_set_cache is not None and cached_jwk_set is not None:
                jwk_set_cache.put(cached_jwk_set)
        finally:
            with self._refresh_condition:
                self._refreshing = False
                self._refreshing_kid = None
                self._refresh_generation += 1
                if refresh_error is None:
                    self._last_refresh_error = None
                else:
                    is_connection_error = isinstance(refresh_error, jwt.exceptions.PyJWKClientConnectionError)
                    self._last_refresh_error = (is_connection_error, str(refresh_error))
                self._next_refresh_at = time.monotonic() + self._refresh_interval
                if signing_keys:
                    self._record_keys(signing_keys)
                self._refresh_condition.notify_all()

        return signing_keys, refresh_error

    def _resolved_key(self, signing_keys: list[jwt.PyJWK], kid: str) -> jwt.PyJWK:
        signing_key = self.match_kid(signing_keys, kid)
        if signing_key is None:
            self._record_missing_key(kid)
            raise self._missing_key_error()
        return signing_key

    def _resolved_key_after_shared_refresh(self, kid: str) -> jwt.PyJWK:
        with self._refresh_condition:
            if self._last_refresh_error is not None:
                is_connection_error, message = self._last_refresh_error
                if is_connection_error:
                    raise jwt.exceptions.PyJWKClientConnectionError(message)
                raise jwt.exceptions.PyJWKClientError(message)
            signing_keys = self.get_signing_keys()
            self._record_keys(signing_keys)
            return self._resolved_key(signing_keys, kid)

    def get_signing_key(self, kid: str) -> jwt.PyJWK:
        if not kid:
            raise self._missing_key_error()

        with self._refresh_condition:
            signing_keys, had_cached_jwks = self._cached_signing_keys()
            signing_key = self.match_kid(signing_keys, kid)
            if signing_key is not None:
                return signing_key
            if not had_cached_jwks:
                return self._resolved_key(signing_keys, kid)
            if kid in self._missing_kids:
                raise self._missing_key_error()
            perform_refresh = self._claim_refresh(kid)

        if not perform_refresh:
            return self._resolved_key_after_shared_refresh(kid)

        signing_keys, refresh_error = self._refresh_signing_keys()
        if refresh_error is not None:
            raise refresh_error
        return self._resolved_key(signing_keys, kid)


@cache
def get_jwks_client(jwks_uri: str) -> jwt.PyJWKClient:
    """Return a shared JWKS client with PyJWT's key-set cache."""
    return CoalescingPyJWKClient(jwks_uri)


@dataclass
class AuthenticationData:
    issuer: str
    subject: str
    audience: str
    issued_at: dt.datetime
    expires_at: dt.datetime
    grant_type: str | None

    @classmethod
    def from_dict(cls, data: dict[Any, Any]) -> Self:
        return cls(
            issuer=data["iss"],
            subject=data["sub"],
            audience=data["aud"],
            issued_at=dt.datetime.fromtimestamp(data["iat"], tz=dt.UTC),
            expires_at=dt.datetime.fromtimestamp(data["exp"], tz=dt.UTC),
            grant_type=data.get("gty"),
        )


@dataclass
class JsonWebToken:
    """Validate Cloudflare Access JSON Web Token using PyJWT."""

    jwt_access_token: str
    audience = cf_access_settings.audience
    jwks_uri = f"{cf_access_settings.team_domain}/cdn-cgi/access/certs"
    algorithm: str = "RS256"

    def validate(self) -> AuthenticationData:
        try:
            jwks_client = get_jwks_client(self.jwks_uri)
            jwt_signing_key = jwks_client.get_signing_key_from_jwt(self.jwt_access_token).key

            payload = jwt.decode(
                self.jwt_access_token,
                jwt_signing_key,
                audience=cf_access_settings.audience,
                issuer=cf_access_settings.team_domain,
                algorithms=[self.algorithm],
            )
        except jwt.exceptions.PyJWKClientConnectionError as err:
            raise UnableCredentialsException from err
        except (jwt.exceptions.PyJWKClientError, jwt.exceptions.InvalidTokenError) as err:
            raise BadCredentialsException from err

        auth_data = AuthenticationData.from_dict(payload)

        # Service tokens identify themselves with common_name; interactive
        # identities use email. Cloudflare always supplies sub as a fallback.
        auth_data.subject = payload.get("common_name") or payload.get("email") or payload["sub"]

        return auth_data
