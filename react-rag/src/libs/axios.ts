import axios, { type InternalAxiosRequestConfig } from "axios";

const API_BASE = import.meta.env.VITE_API_URL ?? "";

// 쿠키 기반 리프레시를 위해 전역으로 허용해도 됨(쿠키 Path=/auth/라서 다른 경로엔 안 붙음)
const instance = axios.create({ baseURL: API_BASE, withCredentials: true });

type RetriableConfig = InternalAxiosRequestConfig & { _retry?: boolean };

// --- 토큰 스토리지 (Access만) ---
const tokenStore = {
  getAccess() { return localStorage.getItem("accessToken"); },
  set(access: string) { localStorage.setItem("accessToken", access); },
  clear() { localStorage.removeItem("accessToken"); },
};

// --- Error 래퍼 ---
function toError(x: unknown): Error {
  if (x instanceof Error) return x;
  if (typeof x === "string") return new Error(x);
  try { return new Error(JSON.stringify(x)); } catch { return new Error("Request failed"); }
}

// pathname만 안전 추출
function resolvePath(raw: string): string {
  try { return new URL(raw, API_BASE || window.location.origin).pathname; }
  catch { return raw; }
}

// 로그인 리다이렉트 중복 방지
let redirectingToLogin = false;
function goLoginOnce() {
  if (window.location.pathname === "/login") return;
  if (redirectingToLogin) return;
  redirectingToLogin = true;
  window.location.href = "/login";
}

// --- 요청 인터셉터: Access 자동 주입 ---
instance.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const access = tokenStore.getAccess();

  const path = resolvePath(config.url ?? "");
  const isAuthEndpoint =
    path.startsWith("/api/auth/exchange") ||
    path.startsWith("/api/auth/refresh") ||
    path.startsWith("/api/auth/logout");

  if (!isAuthEndpoint && access) {
    config.headers = config.headers ?? {};
    (config.headers as Record<string, string>).Authorization = `Bearer ${access}`;
  } else if (isAuthEndpoint) {
    // auth 엔드포인트엔 Authorization 헤더를 넣지 않음(특히 /refresh)
    if (config.headers && "Authorization" in config.headers) {
      delete (config.headers as Record<string, string>).Authorization;
    }
    // 쿠키 기반 호출을 위해 보장
    (config as any).withCredentials = true;
  }
  return config;
});

// --- 401 동시성 제어 ---
let isRefreshing = false;
const waitingQueue: Array<(token: string) => void> = [];
const enqueue = (fn: (token: string) => void) => waitingQueue.push(fn);
const flushQueue = (newAccess: string) => { waitingQueue.forEach(fn => fn(newAccess)); waitingQueue.length = 0; };

// --- 실제 리프레시(단일 실행) ---
// 주의: 인터셉터 안 타게 기본 axios 사용 + withCredentials
async function refreshAccessTokenOnce(): Promise<void> {
  // Refresh는 HttpOnly 쿠키로만 보냄 — 헤더 금지
  const { data } = await axios.post(
    `${API_BASE}/api/auth/refresh`,
    null,
    { withCredentials: true } // 쿠키 전송
  );
  // 백엔드가 access 또는 accessToken 중 하나를 내려줄 수 있으니 둘 다 대응
  const newAccess: string | undefined = data?.access ?? data?.accessToken;
  if (!newAccess) throw new Error("invalid refresh response");
  tokenStore.set(newAccess);
}

// --- 응답 인터셉터: 401 처리 ---
instance.interceptors.response.use(
  (res) => res,
  async (err: unknown) => {
    if (!axios.isAxiosError(err) || !err.response) throw toError(err);

    const { response: res } = err;
    const original = (err.config || {}) as RetriableConfig;

    const path = resolvePath(original.url ?? "");
    const isAuthEndpoint =
      path.startsWith("/api/auth/exchange") ||
      path.startsWith("/api/auth/refresh") ||
      path.startsWith("/api/auth/logout");

    const bodyError = (res.data as any)?.error ?? "";
    const isBlacklisted = typeof bodyError === "string" && bodyError.includes("로그아웃된 토큰");

    if (res.status === 401) {
      // auth 엔드포인트에서 401 → 즉시 로그인 유도
      if (isAuthEndpoint) {
        tokenStore.clear();
        flushQueue("");
        goLoginOnce();
        throw new Error("auth endpoint 401");
      }

      // 이미 재시도 했거나 블랙리스트면 종료
      if (original._retry || isBlacklisted) {
        tokenStore.clear();
        flushQueue("");
        goLoginOnce();
        throw new Error("unauthorized");
      }

      // 로그인 페이지 자체에선 리프레시 시도 안 함
      if (window.location.pathname === "/login") {
        throw new Error("unauthorized on login");
      }

      original._retry = true;

      // 동시 401 → 단일 리프레시
      if (!isRefreshing) {
        isRefreshing = true;
        try {
          await refreshAccessTokenOnce();
        } catch (e) {
          tokenStore.clear();
          flushQueue("");
          goLoginOnce();
          isRefreshing = false;
          throw toError(e);
        }
        isRefreshing = false;
        flushQueue(tokenStore.getAccess() || "");
      }

      // 리프레시 완료 후 원 요청 재시도
      return new Promise((resolve, reject) => {
        enqueue((newAccess) => {
          if (!newAccess) return reject(new Error("relogin"));
          original.headers = original.headers ?? {};
          (original.headers as Record<string, string>).Authorization = `Bearer ${newAccess}`;
          resolve(instance(original));
        });
      });
    }

    if (res.status === 403) {
      throw new Error("Forbidden");
    }

    throw toError(err);
  }
);

export default instance;
