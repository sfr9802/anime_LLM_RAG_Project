// features/auth/pages/LoginPage.tsx
import React, { useState } from "react";
import OAuthLoginButton from "../components/OAuthLoginButton";
import useOAuthListener from "../hooks/useOAuthListener";

const LoginPage: React.FC = () => {
  const [error, setError] = useState<string | null>(null);

  useOAuthListener(
    (accessToken: string, refreshToken?: string) => {
      localStorage.setItem("accessToken", accessToken);
      if (refreshToken) localStorage.setItem("refreshToken", refreshToken);
      window.location.href = "/"; // 로그인 후 메인으로
    },
    (reason) => {
      // 실패 시 에러를 띄워두면 팝업-교환 단계 문제를 파악하기 쉬움
      setError(`로그인 실패: ${reason}`);
    }
  );

  return (
    <div style={{ padding: 16 }}>
      <h2>OAuth2 로그인</h2>
      {error && <p style={{ color: "crimson" }}>{error}</p>}
      <OAuthLoginButton />
    </div>
  );
};

export default LoginPage;
