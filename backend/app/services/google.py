"""Google Sign-In: OAuth 2.0 authorization-code flow with PKCE + OpenID Connect ID-token verification, all server-side.
The browser never supplies identity data: we exchange the code ourselves and verify the ID token's signature (Google's
JWKS), issuer, audience, expiry and nonce before trusting a single claim."""
import base64
import hashlib
import logging
import secrets
import time
from urllib.parse import urlencode

import httpx
import jwt

from app.core.config import get_settings

log = logging.getLogger("recall.google")
settings = get_settings()
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")
_jwks_cache: dict = {"at": 0.0, "keys": {}}


class GoogleError(Exception):
    """Any problem with the Google exchange. Its message is safe to log, not to show."""


def new_pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def build_auth_url(state: str, nonce: str, challenge: str) -> str:
    return AUTH_URL + "?" + urlencode({
        "client_id": settings.google_client_id, "redirect_uri": settings.google_redirect_uri, "response_type": "code",
        "scope": "openid email profile", "state": state, "nonce": nonce, "code_challenge": challenge,
        "code_challenge_method": "S256", "prompt": "select_account"})


def exchange_code(code: str, verifier: str) -> str:
    """Trade the authorization code for an ID token (server-to-server, using the client secret)."""
    try:
        r = httpx.post(TOKEN_URL, data={"code": code, "client_id": settings.google_client_id, "client_secret": settings.google_client_secret,
                                        "redirect_uri": settings.google_redirect_uri, "grant_type": "authorization_code", "code_verifier": verifier}, timeout=10)
    except httpx.HTTPError as e:
        raise GoogleError(f"token endpoint unreachable: {e.__class__.__name__}")
    if r.status_code != 200 or "id_token" not in r.json():
        raise GoogleError(f"token exchange failed ({r.status_code})")
    return r.json()["id_token"]


def fetch_jwks() -> dict:
    try:
        r = httpx.get(JWKS_URL, timeout=10)
        r.raise_for_status()
        return {k["kid"]: k for k in r.json()["keys"]}
    except (httpx.HTTPError, KeyError, ValueError) as e:
        raise GoogleError(f"could not load Google signing keys: {e.__class__.__name__}")


def _key_for(kid: str):
    if kid not in _jwks_cache["keys"] or time.time() - _jwks_cache["at"] > 3600:
        _jwks_cache.update(keys=fetch_jwks(), at=time.time())
    jwk = _jwks_cache["keys"].get(kid)
    if jwk is None:
        raise GoogleError("unknown signing key")
    return jwt.PyJWK(jwk).key


def verify_id_token(id_token: str, nonce: str) -> dict:
    """Signature (RS256), audience = our client id, issuer, expiry, nonce and a verified e-mail are all REQUIRED."""
    try:
        header = jwt.get_unverified_header(id_token)
        if header.get("alg") != "RS256" or not header.get("kid"):
            raise GoogleError("unexpected token algorithm")
        claims = jwt.decode(id_token, _key_for(header["kid"]), algorithms=["RS256"], audience=settings.google_client_id,
                            options={"require": ["exp", "iat", "iss", "aud", "sub"]}, leeway=30)
    except jwt.PyJWTError as e:
        raise GoogleError(f"invalid id_token: {e.__class__.__name__}")
    if claims.get("iss") not in ISSUERS:
        raise GoogleError("bad issuer")
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise GoogleError("nonce mismatch")
    if not claims.get("email") or claims.get("email_verified") is not True:
        raise GoogleError("e-mail not verified by Google")
    return claims
