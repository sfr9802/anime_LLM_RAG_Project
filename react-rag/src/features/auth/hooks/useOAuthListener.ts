// features/auth/hooks/useOAuthListener.ts
import { useEffect } from "react";

type OAuthSuccessMsg = {
  type: "oauth-success";
  accessToken: string;
  refreshToken?: string;
};
type OAuthFailMsg = { type: "oauth-fail"; reason: string };
type OAuthMsg = OAuthSuccessMsg | OAuthFailMsg;

export default function useOAuthListener(
  onSuccess: (accessToken: string, refreshToken?: string) => void,
  onFail?: (reason: string) => void
) {
  useEffect(() => {
    const handler = (ev: MessageEvent<OAuthMsg>) => {
      // 같은 오리진만 수신
      if (ev.origin !== window.location.origin) return;
      const data = ev.data;
      if (data?.type === "oauth-success" && data.accessToken) {
        onSuccess(data.accessToken, data.refreshToken);
      } else if (data?.type === "oauth-fail") {
        onFail?.(data.reason ?? "unknown");
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [onSuccess, onFail]);
}
