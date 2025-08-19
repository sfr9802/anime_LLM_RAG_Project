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
 */
export function useMe(enabled = true) {
  const [user, setUser] = useState<MeResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<Error | null>(null);

  const refetch = useCallback(async () => {
    const token = localStorage.getItem("accessToken");
    if (!enabled || !token) {
      setUser(null);
      setLoading(false);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await fetchMe();
      setUser(res ?? null);
    } catch (e) {
      setError(toError(e));
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, [enabled]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const token = localStorage.getItem("accessToken");
      if (!enabled || !token) {
        if (!cancelled) {
          setUser(null);
          setLoading(false);
          setError(null);
        }
        return;
      }
      if (!cancelled) {
        setLoading(true);
        setError(null);
      }
      try {
        const res = await fetchMe();
        if (!cancelled) setUser(res ?? null);
      } catch (e) {
        if (!cancelled) {
          setError(toError(e));
          setUser(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [enabled]);

  return { user, loading, error, refetch };
}

export default useMe;
