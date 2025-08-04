// libs/axios.ts

import axios from "axios";

// ✅ axios 인스턴스 생성
const instance = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? "",
});

// ✅ 요청 시 accessToken 자동 삽입
instance.interceptors.request.use((config) => {
  const accessToken = localStorage.getItem("accessToken");
  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`;
  }
  return config;
});

// ✅ 응답 인터셉터: 401 발생 시 자동 refresh 시도
instance.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;

    // 🚫 로그아웃 요청에는 refresh 시도 금지
    if (
      originalRequest?.url?.includes("/api/auth/logout") ||
      originalRequest?._retry
    ) {
      return Promise.reject(new Error("Refresh token missing"));
    }

    if (error.response?.status === 401) {
      originalRequest._retry = true;

      const refreshToken = localStorage.getItem("refreshToken");
      if (!refreshToken) {
        localStorage.clear();
        window.location.href = "/login";
        return Promise.reject(new Error("Refresh token missing"));
      }

      try {
        const { data } = await axios.post(
          `${import.meta.env.VITE_API_URL}/api/auth/refresh`,
          null,
          {
            headers: {
              Authorization: `Bearer ${refreshToken}`,
            },
          }
        );

        const { accessToken, refreshToken: newRefreshToken } = data;

        // 📝 토큰 저장
        localStorage.setItem("accessToken", accessToken);
        localStorage.setItem("refreshToken", newRefreshToken);

        // 📝 원 요청 Authorization 갱신
        originalRequest.headers.Authorization = `Bearer ${accessToken}`;

        // 📝 원 요청 재시도
        return instance(originalRequest);
      } catch (refreshErr) {
        console.error("[Auth] Refresh failed", refreshErr);
        localStorage.clear();
        window.location.href = "/login";
        return Promise.reject(
          refreshErr instanceof Error
            ? refreshErr
            : new Error("Token refresh failed")
        );
      }
    }

    return Promise.reject(
      error instanceof Error ? error : new Error("API Error")
    );
  }
);

export default instance;
