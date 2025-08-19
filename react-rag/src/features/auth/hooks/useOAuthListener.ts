// features/auth/hooks/useOAuthListener.ts
import { useEffect } from "react";

export default function useOAuthListener(onSuccess: (a: string, r?: string) => void) {
  useEffect(() => {
    const handler = (ev: MessageEvent) => {
      if (ev.origin !== window.location.origin) return;
      const data = ev.data;
      if (data?.type === "oauth-success" && data?.accessToken) {
        onSuccess(data.accessToken, data.refreshToken);
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [onSuccess]);
}
