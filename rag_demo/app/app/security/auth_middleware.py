# app/app/security/auth_middleware.py
import os
import jwt
from jwt import InvalidTokenError, ExpiredSignatureError
from typing import Tuple
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

def _is_local_host(host: str | None) -> bool:
    if not host:
        return False
    host = host.lower()
    if host in ("127.0.0.1", "::1", "localhost"):
        return True
    # 사내/로컬 대역도 허용하고 싶으면 아래 범위를 쓰면 됨
    if host.startswith("192.168.") or host.startswith("10.") or host.startswith("172.16.") or host.startswith("172.17.") \
       or host.startswith("172.18.") or host.startswith("172.19.") or host.startswith("172.20.") or host.startswith("172.21.") \
       or host.startswith("172.22.") or host.startswith("172.23.") or host.startswith("172.24.") or host.startswith("172.25.") \
       or host.startswith("172.26.") or host.startswith("172.27.") or host.startswith("172.28.") or host.startswith("172.29.") \
       or host.startswith("172.30.") or host.startswith("172.31."):
        return True
    return False

def _bypass_mode() -> str:
    # "1/true/on" → 전역 바이패스, "local" → 로컬 접속만 바이패스
    return (os.getenv("AUTH_BYPASS", "0") or "").strip().lower()

class AuthOnlyMiddleware(BaseHTTPMiddleware):
    """
    전역 JWT 재검증(HS256). 유효성만 확인하고 라우터는 건드리지 않음.
    - protected_prefixes 경로만 보호
    - public_paths는 화이트리스트
    - OPTIONS, /docs, /openapi.json 등은 통과
    - ENV AUTH_BYPASS=1/true/on → 전체 바이패스
      ENV AUTH_BYPASS=local      → 로컬에서 온 요청만 바이패스
    """
    def __init__(
        self,
        app,
        *,
        secret: str | None = None,
        protected_prefixes: Tuple[str, ...] = ("/rag", "/search", "/admin", "/api"),
        public_paths: Tuple[str, ...] = ("/health", "/docs", "/redoc", "/openapi.json", "/debug", "/rag/healthz"),
        leeway: int = 5,
    ):
        super().__init__(app)
        self.secret = (secret or os.getenv("JWT_SECRET") or "").strip() or "dev-secret-change-me"
        self.protected_prefixes = protected_prefixes
        self.public_paths = public_paths
        self.leeway = leeway

    async def dispatch(self, request, call_next):
        path = request.url.path
        method = request.method.upper()

        # ===== BYPASS =====
        mode = _bypass_mode()
        if mode in ("1", "true", "yes", "on"):
            return await call_next(request)
        if mode == "local" and _is_local_host(getattr(request.client, "host", None)):
            return await call_next(request)

        # 공개 경로/프리플라이트 통과
        if method == "OPTIONS" or any(path.startswith(p) for p in self.public_paths):
            return await call_next(request)

        # 보호 대상만 검증
        if not any(path.startswith(p) for p in self.protected_prefixes):
            return await call_next(request)

        # Authorization: Bearer <token>
        auth = (request.headers.get("authorization") or "").strip()
        if not auth.lower().startswith("bearer "):
            return JSONResponse({"error": "missing token"}, status_code=401)
        token = auth[7:].strip()
        if not token:
            return JSONResponse({"error": "missing token"}, status_code=401)

        try:
            claims = jwt.decode(
                token,
                self.secret,
                algorithms=["HS256"],
                options={"require": ["exp"], "verify_exp": True},
                leeway=self.leeway,
            )
            request.state.claims = claims
            request.state.roles = _extract_roles(claims)
        except ExpiredSignatureError:
            return JSONResponse({"error": "token expired"}, status_code=401)
        except InvalidTokenError as e:
            return JSONResponse({"error": f"invalid token: {e}"}, status_code=401)

        return await call_next(request)

def _extract_roles(payload: dict) -> list[str]:
    roles = set()
    r = payload.get("roles")
    if isinstance(r, list):
        roles.update(str(x).upper() for x in r)
    elif isinstance(r, str):
        roles.update(s.upper() for s in r.replace(",", " ").split() if s)
    a = payload.get("authorities")
    if isinstance(a, list):
        for v in a:
            s = str(v).upper()
            if s.startswith("ROLE_"):
                roles.add(s[5:])
    return sorted(roles)
