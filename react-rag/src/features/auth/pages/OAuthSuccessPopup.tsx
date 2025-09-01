// features/auth/pages/OAuthSuccessPopup.tsx
import { useEffect, useRef, useState } from "react";
const API_BASE = import.meta.env.VITE_API_URL ?? "";
const DEBUG = import.meta.env.VITE_OAUTH_POPUP_DEBUG === "1"; // 실패 시 창 안 닫기용

export default function OAuthSuccessPopup() {
  const [msg, setMsg] = useState("교환 중...");
  const ran = useRef(false); // 🔒 중복 실행 방지

  const postToOpener = (payload: any) => {
    
    if (window.opener && !window.opener.closed) {
      window.opener.postMessage(payload, window.location.origin);
    }
  };

  const closeSoon = () => {
    console.log("[popup] opener exists?", !!window.opener && !window.opener.closed);
    if (DEBUG) return;            // 디버그면 안 닫음
    setTimeout(() => window.close(), 400);
  };

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;

    (async () => {
      const url = new URL(window.location.href);
      const code = url.searchParams.get("code");
      const error = url.searchParams.get("error");

      if (error) {
        setMsg(`OAuth 실패: ${error}`);
        postToOpener({ type: "oauth-fail", reason: error });
        return; // ❌ 실패 시 창 유지
      }
      if (!code) {
        setMsg("code 없음 (리다이렉트 실패 또는 잘못된 URL)");
        return; // ❌ 닫지 않음
      }

      try {
        const resp = await fetch(`${API_BASE}/api/auth/exchange?code=${encodeURIComponent(code)}`, {
          headers: { Accept: "application/json" },
          credentials: "omit",
        });
        if (!resp.ok) throw new Error(`exchange ${resp.status}`);
        const data = await resp.json();
        if (!data?.accessToken) throw new Error("invalid exchange response");

        postToOpener({ type: "oauth-success", accessToken: data.accessToken });
        setMsg("성공! 창을 닫습니다…");
        closeSoon(); // ✅ 성공 시에만 닫기
      } catch (e: any) {
        setMsg(`교환 실패: ${e?.message ?? e}`);
        postToOpener({ type: "oauth-fail", reason: String(e) });
        // ❌ 실패 시엔 기본적으로 닫지 않음(디버깅 쉽게)
      }
    })();
  }, []);

  return (
    <div style={{ padding: 16 }}>
      <h3>OAuth 처리</h3>
      <p>{msg}</p>
      {DEBUG && <p style={{color:"#999"}}>DEBUG 모드: 실패 시 자동으로 닫지 않습니다.</p>}
    </div>
  );
}
