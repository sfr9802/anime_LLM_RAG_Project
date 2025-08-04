import { useEffect, useState } from "react";
import { fetchMe } from "@/features/auth/services/authApi";
import type { MeResponse } from "@/features/auth/types/Auth";

export function useMe() {
  const [user, setUser] = useState<MeResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    const token = localStorage.getItem("accessToken");
    if (!token) {
      setUser(null);
      setLoading(false);
      return;
    }

    fetchMe()
      .then((res) => {
        if (res) {
          setUser(res);
        } else {
          setUser(null);
        }
      })
      .catch((err) => {
        console.warn("useMe 오류:", err);
        setError(err);
      })
      .finally(() => {
        setLoading(false);
      });
  }, []);

  return { user, loading, error };
}
