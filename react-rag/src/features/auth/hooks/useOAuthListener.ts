import { useEffect } from "react";

const useOAuthListener = (onReceiveToken: (accessToken: string, refreshToken?: string) => void) => {
  useEffect(() => {
    const listener = (e: MessageEvent) => {
      if (e.origin !== import.meta.env.VITE_OAUTH_URL) return;
      const { accessToken, refreshToken } = e.data || {};

      if (accessToken) {
        onReceiveToken(accessToken, refreshToken);
      }
    };

    window.addEventListener("message", listener);
    return () => window.removeEventListener("message", listener);
  }, [onReceiveToken]);
};

export default useOAuthListener;
