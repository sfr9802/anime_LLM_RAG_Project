// features/auth/services/authApi.ts
import axios from "@/libs/axios";
import type { MeResponse } from "../types/Auth";

export const fetchMe = async (): Promise<MeResponse | null> => {
  try {
    const res = await axios.get<MeResponse>("/api/users/me");
    return res.data;
  } catch (err) {
    console.warn("fetchMe 실패", err);
    return null;
  }
};
