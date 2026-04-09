"""JWT authentication dependency for FastAPI routes."""
from __future__ import annotations
import base64, logging
from typing import Optional
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.runtime.config import Settings

logger = logging.getLogger(__name__)
_bearer_scheme = HTTPBearer(auto_error=False)

def _get_settings(request: Request) -> Settings:
    return request.app.state.settings

def _decode_secret(settings: Settings) -> bytes:
    secret = settings.jwt_secret
    if settings.jwt_secret_b64.lower() in ("true", "1", "yes"):
        return base64.b64decode(secret)
    return secret.encode("utf-8")

async def require_auth(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> dict:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    settings = _get_settings(request)
    secret = _decode_secret(settings)
    try:
        return jwt.decode(credentials.credentials, secret, algorithms=["HS256"],
                          audience=settings.jwt_aud, issuer=settings.jwt_iss, leeway=60)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError as e:
        logger.warning("JWT validation failed: %s", e)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
