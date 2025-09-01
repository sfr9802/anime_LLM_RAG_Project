# app/app/security/auth_middleware.py
import os, base64, binascii, jwt
from jwt import InvalidTokenError, ExpiredSignatureError
from typing import Tuple, Optional
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import hashlib, logging

log = logging.getLogger("auth")

def _env_true(name: str, default="0") -> bool:
    val = (os.getenv(name, default) or "").strip().lower()
    return val in ("1","true","yes","on")

class AuthOnlyMiddleware(BaseHTTPMiddleware):
    def __init__(
        self, app, *,
        secret: Optional[str] = None,
        protected_prefixes: Tuple[str, ...] = ("/rag", "/search", "/admin", "/api"),
        public_paths: Tuple[str, ...] = ("/health", "/docs", "/redoc", "/openapi.json", "/debug", "/rag/healthz"),
        leeway: int = 30,
    ):
        super().__init__(app)

        raw = secret if secret is not None else os.getenv("JWT_SECRET")
        if raw is None:
            raise RuntimeError("JWT_SECRET is not set")

        s = str(raw).strip()
        if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
            s = s[1:-1]  # .env에 따옴표가 있었다면 제거

        if _env_true("JWT_SECRET_B64", "0"):
            try:
                secret_bytes = base64.b64decode(s, validate=True)
            except binascii.Error:
                raise RuntimeError("JWT_SECRET_B64=true인데 Base64 디코드 실패")
        else:
            secret_bytes = s.encode("utf-8")

        if len(secret_bytes) < 32:
            raise RuntimeError("JWT_SECRET 길이 너무 짧음(>=32 bytes)")

        # 🔎 디버깅용 키 지문(노출 안전한 해시)
        log.info("[AUTH] key.len=%d, key.fp=%s",
                 len(secret_bytes),
                 hashlib.sha256(secret_bytes).hexdigest()[:16])

        self.secret_bytes = secret_bytes
        self.aud = (os.getenv("JWT_AUD") or "frontend").strip() or None
        self.iss = (os.getenv("JWT_ISS") or "arin").strip() or None
        self.protected_prefixes = protected_prefixes
        self.public_paths = public_paths
        self.leeway = leeway

    async def dispatch(self, request, call_next):
        path = request.url.path
        if request.method == "OPTIONS" or any(path.startswith(p) for p in self.public_paths):
            return await call_next(request)
        if not any(path.startswith(p) for p in self.protected_prefixes):
            return await call_next(request)

        auth = (request.headers.get("authorization") or "").strip()
        if not auth.lower().startswith("bearer "):
            return JSONResponse({"error": "missing token"}, status_code=401)
        token = auth[7:].strip()

        try:
            options = {"require": ["exp"], "verify_exp": True, "verify_aud": bool(self.aud)}
            claims = jwt.decode(
                token,
                self.secret_bytes,
                algorithms=["HS256"],
                audience=self.aud if self.aud else None,
                issuer=self.iss if self.iss else None,
                leeway=self.leeway,
                options=options,
            )
            request.state.claims = claims
        except ExpiredSignatureError:
            return JSONResponse({"error": "token expired"}, status_code=401)
        except InvalidTokenError as e:
            return JSONResponse({"error": f"invalid token: {e}"}, status_code=401)

        return await call_next(request)
