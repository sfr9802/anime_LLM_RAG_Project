import React from "react";
import OAuthLoginButton from "../components/OAuthLoginButton";
import useOAuthListener from "../hooks/useOAuthListener";

const LoginPage: React.FC = () => {
  
  useOAuthListener((accessToken, refreshToken) => {
    localStorage.setItem("accessToken", accessToken);
    if (refreshToken) localStorage.setItem("refreshToken", refreshToken);
    window.location.href = "/"; // 🔄 강제 새로고침으로 MainLayout 초기화
  });

  return (
    <div>
      <h2>OAuth2 로그인</h2>
      <OAuthLoginButton />
    </div>
  );
};

export default LoginPage;
