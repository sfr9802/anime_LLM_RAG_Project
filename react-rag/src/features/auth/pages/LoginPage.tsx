// features/auth/pages/LoginPage.tsx
import React from "react";
import OAuthLoginButton from "../components/OAuthLoginButton";
import useOAuthListener from "../hooks/useOAuthListener";

const LoginPage: React.FC = () => {
  useOAuthListener((accessToken, refreshToken) => {
    localStorage.setItem("accessToken", accessToken);
    if (refreshToken) localStorage.setItem("refreshToken", refreshToken);
    window.location.href = "/"; // 로그인 후 메인으로
  });

  return (
    <div style={{ padding: 16 }}>
      <h2>OAuth2 로그인</h2>
      <OAuthLoginButton />
    </div>
  );
};

export default LoginPage;
