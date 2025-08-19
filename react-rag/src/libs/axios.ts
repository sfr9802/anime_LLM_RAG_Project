// libs/axios.ts
import axios, { type InternalAxiosRequestConfig } from "axios";

const API_BASE = import.meta.env.VITE_API_URL ?? "";

type RetriableConfig = InternalAxiosRequestConfig & { _retry?: boolean };

const instance = axios.create({ baseURL: API_BASE });

// --- 토큰 스토리지 util ---
const tokenStore = {
  getAccess() { return localStorage.getItem("accessToken"); },
  getRefresh() { return localStorage.getItem("refreshToken"); },
  set(access: string, refresh?: string) {
    localStorage.setItem("accessToken", access);
    if (refresh) localStorage.setItem("refreshToken", refresh);
  },
  clear() {
    localStorage.removeItem("accessToken");
    localStorage.removeItem("refreshToken");
  },
};

// --- Error 래퍼 (S6671 대응) ---
function toError(x: unknown): Error {
  if (x instanceof Error) return x;
  if (typeof x === "string") return new Error(x);
  try { return new Error(JSON.stringify(x)); } catch { return new Error("Request failed"); }
}

// URL 또는 상대경로에서 pathname만 안전하게 뽑기
function resolvePath(raw: string): string {
  try { return new URL(raw, API_BASE || window.location.origin).pathname; }
  catch { return raw; }
}

// 로그인 리다이렉트 중복 방지 플래그
let redirectingToLogin = false;
function goLoginOnce() {
  if (window.location.pathname === "/login") return;
  if (redirectingToLogin) return;
  redirectingToLogin = true;
  window.location.href = "/login";
}

// --- 요청 인터셉터: access 자동 주입 ---
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
  }
  return config;
});

// --- 401 동시성 제어용 큐 ---
let isRefreshing = false;
const waitingQueue: Array<(token: string) => void> = [];

function enqueue(fn: (token: string) => void) { waitingQueue.push(fn); }
function flushQueue(newAccess: string) { for (const fn of waitingQueue) fn(newAccess); waitingQueue.length = 0; }

// --- 실제 리프레시 요청(단일 실행) ---
// 주의: 기본 axios 사용(이 인스턴스 인터셉터 안 탐)
async function refreshAccessTokenOnce(): Promise<void> {
  const refresh = tokenStore.getRefresh();
  if (!refresh) throw new Error("no refresh token");

  const { data } = await axios.post(
    `${API_BASE}/api/auth/refresh`,
    null,
    { headers: { Authorization: `Bearer ${refresh}` } }
  );
  const { accessToken, refreshToken: newRefresh } = data || {};
  if (!accessToken) throw new Error("invalid refresh response");
  tokenStore.set(accessToken, newRefresh);
}

// --- 응답 인터셉터: 401 처리 ---
instance.interceptors.response.use(
  (res) => res,
  async (err: unknown) => {
    if (!axios.isAxiosError(err) || !err.response) {
      throw toError(err);
    }
    const res = err.response;
    const original = (err.config || {}) as RetriableConfig;

    // 호출 경로 식별(무한 루프 방지용)
    const path = resolvePath(original.url ?? "");
    const isAuthEndpoint =
      path.startsWith("/api/auth/exchange") ||
      path.startsWith("/api/auth/refresh") ||
      path.startsWith("/api/auth/logout");

    const bodyError = (res.data as any)?.error ?? "";
    const isBlacklisted = typeof bodyError === "string" && bodyError.includes("로그아웃된 토큰");

    if (res.status === 401) {
      // ✅ auth 엔드포인트 자체에서의 401은 재시도 금지, 즉시 로그아웃
      if (isAuthEndpoint) {
        tokenStore.clear();
        flushQueue("");
        goLoginOnce();
        throw new Error("auth endpoint 401");
      }

      // ✅ 이미 한 번 재시도했거나 블랙리스트면 종료
      if (isBlacklisted || original._retry) {
        tokenStore.clear();
        flushQueue("");
        goLoginOnce();
        throw new Error("unauthorized");
      }

      // ✅ 로그인 화면에서는 리프레시 루틴 자체를 돌지 않음
      if (window.location.pathname === "/login") {
        throw new Error("unauthorized on login");
      }

      original._retry = true;

      // 동시 401 → 단일 리프레시
      if (!isRefreshing) {
        isRefreshing = true;
        try {
          await refreshAccessTokenOnce();
          isRefreshing = false;
          flushQueue(tokenStore.getAccess() || "");
        } catch (e) {
          isRefreshing = false;
          tokenStore.clear();
          flushQueue("");
          goLoginOnce();
          throw toError(e);
        }
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
