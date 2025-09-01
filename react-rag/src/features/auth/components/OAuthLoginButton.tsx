// features/auth/components/OAuthLoginButton.tsx
const OAUTH_BASE =
  import.meta.env.VITE_OAUTH_URL ?? import.meta.env.VITE_API_URL ?? "";
const FRONT_REDIRECT = `${window.location.origin}/oauth/success-popup`;

function getTopWindow(): Window {
  try {
    return window.top ?? window;
  } catch {
    return window; // cross-origin 차단 시
  }
}

export default function OAuthLoginButton() {
  const href = `${OAUTH_BASE}/oauth2/authorization/google?front=${encodeURIComponent(
    FRONT_REDIRECT
  )}&state=popup`;

  const openPopup = () => {
    const topWin = getTopWindow();
    const w = 520;
    const h = 680;

    const outerH =
      typeof topWin.outerHeight === "number" ? topWin.outerHeight : window.outerHeight;
    const outerW =
      typeof topWin.outerWidth === "number" ? topWin.outerWidth : window.outerWidth;
    const scrY =
      typeof (topWin as any).screenY === "number"
        ? (topWin as any).screenY
        : (window as any).screenY ?? 0;
    const scrX =
      typeof (topWin as any).screenX === "number"
        ? (topWin as any).screenX
        : (window as any).screenX ?? 0;

    const y = Math.round(outerH / 2 + scrY - h / 2);
    const x = Math.round(outerW / 2 + scrX - w / 2);

    // features는 문자열이어야 하므로 템플릿 리터럴로 확정
    void topWin.open(
      href,
      "oauthLogin",
      `width=${w},height=${h},left=${x},top=${y},scrollbars=yes,resizable=yes`
    );
  };

  return <button onClick={openPopup}>Google로 로그인</button>;
}
