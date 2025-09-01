// src/libs/axios.ts
import axios, { type InternalAxiosRequestConfig, type AxiosError } from "axios";

const API_BASE = (import.meta.env.VITE_API_URL ?? "").trim(); // dev에선 보통 ""
// refresh는 인증 쿠키만 필요하므로, API_BASE가 비어있으면 8080으로 폴백
const REFRESH_BASE =
  API_BASE ||
  (import.meta.env.VITE_REFRESH_BASE?.toString().trim() || "http://localhost:8080");

const instance = axios.create({
  baseURL: API_BASE,     // ""면 프런트 오리진 기준 상대경로로 나감 (Vite 프록시 사용 시 OK)
  withCredentials: true, // refresh 쿠키 전송
});

type RetriableConfig = InternalAxiosRequestConfig & { _retry?: boolean };

const AUTH_PATHS = [
  "/oauth2/authorization",
  "/login/oauth2/code",
  "/api/auth/exchange",
  "/api/auth/refresh",
  "/api/auth/logout",
];
const isAuthPath = (p: string) => AUTH_PATHS.some((e) => p.startsWith(e));

const tokenStore = {
  get() {
    return localStorage.getItem("accessToken");
  },
  set(t: string) {
    localStorage.setItem("accessToken", t);
  },
  clear() {
    localStorage.removeItem("accessToken");
  },
};

const toError = (x: unknown): Error => {
  if (x instanceof Error) return x;
  if (typeof x === "string") return new Error(x);
  try {
    return new Error(JSON.stringify(x));
  } catch {
    return new Error("Request failed");
  }
};

const resolvePath = (raw: string): string => {
  try {
    // 절대/상대 URL 모두 안전하게 pathname만 추출
    return new URL(raw, window.location.origin).pathname;
  } catch {
    return raw;
  }
};

let redirectingToLogin = false;
const goLoginOnce = () => {
  if (window.location.pathname === "/login") return;
  if (redirectingToLogin) return;
  redirectingToLogin = true;
  window.location.href = "/login";
};

// ===== 요청 인터셉터 =====
instance.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const path = resolvePath(config.url ?? "");
  if (isAuthPath(path)) {
    // auth 엔드포인트엔 Authorization 헤더 금지(특히 /refresh)
    if (config.headers && "Authorization" in config.headers) {
      delete (config.headers as Record<string, string>).Authorization;
    }
  } else {
    const access = tokenStore.get();
    if (access) {
      config.headers = config.headers ?? {};
      (config.headers as Record<string, string>).Authorization = `Bearer ${access}`;
    }
  }
  return config;
});

// ===== 401 동시성 제어 =====
let isRefreshing = false;
const waiters: Array<(token: string) => void> = [];
const enqueue = (fn: (token: string) => void) => waiters.push(fn);
const flush = (t: string) => {
  waiters.forEach((fn) => fn(t));
  waiters.length = 0;
};

// ===== 실제 리프레시 (인터셉터 우회 + 절대 URL 폴백) =====
async function refreshAccessTokenOnce(): Promise<string> {
  const { data } = await axios.post(
    `${REFRESH_BASE}/api/auth/refresh`,
    null,
    { withCredentials: true } // 쿠키 전송
  );
  // 백엔드 응답 키 방어적으로 처리
  const newAccess: string | undefined = data?.accessToken ?? data?.access;
  if (!newAccess) throw new Error("invalid refresh response");
  tokenStore.set(newAccess);
  return newAccess;
}

function parseAuthError(err: AxiosError) {
  const data = (err.response?.data ?? {}) as any;
  const error = (data?.error ?? "").toString().toUpperCase();
  const message = (data?.message ?? "").toString().toLowerCase();
  return {
    isUnauthorized: err.response?.status === 401,
    isForbidden: err.response?.status === 403,
    isAuthEndpoint: isAuthPath(resolvePath(err.config?.url ?? "")),
    // 재사용/무효/블랙리스트 등은 바로 재로그인
    hardFail:
      error === "UNAUTHORIZED" &&
      (message.includes("reuse") ||
        message.includes("invalid refresh") ||
        message.includes("not a refresh") ||
        message.includes("token blacklisted")),
  };
}

// ===== 응답 인터셉터 =====
instance.interceptors.response.use(
  (res) => res,
  async (err: unknown) => {
    if (!axios.isAxiosError(err) || !err.response) throw toError(err);

    const { isUnauthorized, isForbidden, isAuthEndpoint, hardFail } = parseAuthError(err);
    const original = (err.config || {}) as RetriableConfig;

    // 인증 엔드포인트에서 401 → 바로 재로그인
    if (isAuthEndpoint && isUnauthorized) {
      tokenStore.clear();
      flush("");
      goLoginOnce();
      throw new Error("auth endpoint 401");
    }

    if (isForbidden) throw new Error("Forbidden");
    if (!isUnauthorized) throw toError(err);

    // 이미 재시도했거나 강한 실패면 로그인 유도
    if (original._retry || hardFail) {
      tokenStore.clear();
      flush("");
      goLoginOnce();
      throw new Error("unauthorized");
    }

    // 로그인 화면에서는 리프레시 시도하지 않음
    if (window.location.pathname === "/login") {
      throw new Error("unauthorized on login");
    }

    original._retry = true;

    // 동시 401 → 단일 리프레시
    if (!isRefreshing) {
      isRefreshing = true;
      try {
        const t = await refreshAccessTokenOnce();
        isRefreshing = false;
        flush(t);
      } catch (e) {
        isRefreshing = false;
        tokenStore.clear();
        flush("");
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
);

// ===== 유틸 =====
export function setAccessToken(access: string) {
  tokenStore.set(access);
}
export function clearAccessToken() {
  tokenStore.clear();
}
export async function logout(all = false) {
  try {
    await instance.post(`/api/auth/logout${all ? "?all=true" : ""}`, null, {
      withCredentials: true,
    });
  } finally {
    tokenStore.clear();
  }
}

export default instance;
