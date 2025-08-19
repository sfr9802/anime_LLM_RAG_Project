// features/auth/pages/OAuthSuccessPopup.tsx
import { useEffect, useState } from "react";

const API_BASE = import.meta.env.VITE_API_URL ?? "";

export default function OAuthSuccessPopup() {
  const [msg, setMsg] = useState("교환 중...");

  useEffect(() => {
    const code = new URL(window.location.href).searchParams.get("code");

    const notifyAndClose = (payload: any) => {
      if (window.opener && !window.opener.closed) {
        window.opener.postMessage(payload, window.location.origin);
        setTimeout(() => window.close(), 400);
      } else {
        // 팝업이 아닌 경우(직접 열렸을 때) 최소 동작
        if (payload?.type === "oauth-success") {
          localStorage.setItem("accessToken", payload.accessToken);
          if (payload.refreshToken) localStorage.setItem("refreshToken", payload.refreshToken);
          window.location.replace("/");
        } else {
          window.location.replace("/login");
        }
      }
    };

    (async () => {
      if (!code) {
        setMsg("code 없음");
        return; // ← 팝업 URL이 잘못 들어온 경우. 여기서 끝.
      }
      try {
        const resp = await fetch(`${API_BASE}/api/auth/exchange?code=${encodeURIComponent(code)}`, {
          headers: { Accept: "application/json" },
          credentials: "omit",
        });
        if (!resp.ok) throw new Error(`exchange ${resp.status}`);
        const data = await resp.json();
        const { accessToken, refreshToken } = data || {};
        if (!accessToken) throw new Error("invalid exchange response");

        notifyAndClose({ type: "oauth-success", accessToken, refreshToken });
        setMsg("성공! 창을 닫습니다...");
      } catch (e) {
        console.error("exchange 실패", e);
        setMsg("실패. 창을 닫습니다...");
        notifyAndClose({ type: "oauth-fail", reason: String(e) });
      }
    })();
  }, []);

  return (
    <div style={{ padding: 16 }}>
      <h3>OAuth 처리</h3>
      <p>{msg}</p>
    </div>
  );
}
