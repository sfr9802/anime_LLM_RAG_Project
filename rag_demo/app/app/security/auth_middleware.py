# app/app/security/auth_middleware.py
import os
import jwt
from jwt import InvalidTokenError, ExpiredSignatureError
from typing import Tuple
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

class AuthOnlyMiddleware(BaseHTTPMiddleware):
    """
    전역 JWT 재검증(HS256). 유효성만 확인하고 라우터는 건드리지 않음.
    - protected_prefixes 경로만 보호
    - public_paths는 화이트리스트
    - OPTIONS, /docs, /openapi.json 등은 통과
    """
    def __init__(
        self,
        app,
        *,
        secret: str | None = None,
        protected_prefixes: Tuple[str, ...] = ("/rag", "/search", "/admin", "/api"),
        public_paths: Tuple[str, ...] = ("/health", "/docs", "/redoc", "/openapi.json"),
        leeway: int = 5,
    ):
        super().__init__(app)
        self.secret = (secret or os.getenv("JWT_SECRET") or "").strip()
        if not self.secret:
            # 운영에선 반드시 환경변수로 주입
            self.secret = "dev-secret-change-me"
        self.protected_prefixes = protected_prefixes
        self.public_paths = public_paths
        self.leeway = leeway

    async def dispatch(self, request, call_next):
        path = request.url.path
        method = request.method.upper()

        # 공개 경로/프리플라이트 통과
        if method == "OPTIONS" or any(path.startswith(p) for p in self.public_paths):
            return await call_next(request)

        # 보호 대상만 검증(전부 잠그려면 이 if를 제거)
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
            # 라우터에서 필요하면 꺼내 쓰라고 적재
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
    # authorities: ["ROLE_ADMIN", ...] 지원
    a = payload.get("authorities")
    if isinstance(a, list):
        for v in a:
            s = str(v).upper()
            if s.startswith("ROLE_"):
                roles.add(s[5:])
    return sorted(roles)
