// features/auth/services/authApi.ts
import api from "@/libs/axios";
import type { MeResponse } from "../types/Auth";

export const fetchMe = async (): Promise<MeResponse | null> => {
  try {
    const res = await api.get<MeResponse>("/api/users/me"); // Bearer 자동 부착
    return res.data;
  } catch (err) {
    console.warn("fetchMe 실패", err);
    return null;
  }
};

type TokenPair = { accessToken: string; refreshToken: string };

// OTC 교환
export async function exchangeCode(code: string): Promise<TokenPair> {
  const { data } = await api.get<TokenPair>("/api/auth/exchange", {
    params: { code },
    headers: { Accept: "application/json" },
  });
  return data;
}

// 리프레시
export async function refreshWithBearer(refreshToken: string): Promise<TokenPair> {
  const { data } = await api.post<TokenPair>("/api/auth/refresh", null, {
    headers: { Authorization: `Bearer ${refreshToken}` },
  });
  return data;
}

// 로그아웃
export async function logout(accessToken?: string): Promise<void> {
  await api.post("/api/auth/logout", null, {
    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : undefined,
  });
}
