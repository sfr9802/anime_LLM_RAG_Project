// hooks/useMe.ts
import { useEffect, useState, useCallback } from "react";
import { fetchMe } from "@/features/auth/services/authApi";
import type { MeResponse } from "@/features/auth/types/Auth";

function toError(x: unknown): Error {
  if (x instanceof Error) return x;
  if (typeof x === "string") return new Error(x);
  try { return new Error(JSON.stringify(x)); } catch { return new Error("fetchMe failed"); }
}

/**
 * @param enabled true일 때만 /api/users/me 호출
 *  - access 토큰이 없어도 호출합니다(401→리프레시→재시도는 axios 인터셉터가 처리)
 */
export function useMe(enabled = true) {
  const [user, setUser] = useState<MeResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<Error | null>(null);

  const load = useCallback(async () => {
    if (!enabled) {
      setUser(null);
      setLoading(false);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await fetchMe(); // axios 인스턴스(인터셉터/withCredentials 설정된 것) 사용
      setUser(res ?? null);
    } catch (e) {
      // 리프레시 실패 시 인터셉터가 로그인 리다이렉트까지 처리하므로 여기선 상태만 정리
      setError(toError(e));
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, [enabled]);

  useEffect(() => {
    let active = true;
    (async () => {
      if (!enabled) { setUser(null); setLoading(false); setError(null); return; }
      setLoading(true); setError(null);
      try {
        const res = await fetchMe();
        if (active) setUser(res ?? null);
      } catch (e) {
        if (active) { setError(toError(e)); setUser(null); }
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => { active = false; };
  }, [enabled]);

  // 외부에서 다시 불러야 할 때
  const refetch = useCallback(() => load(), [load]);

  return { user, loading, error, refetch };
}

export default useMe;
