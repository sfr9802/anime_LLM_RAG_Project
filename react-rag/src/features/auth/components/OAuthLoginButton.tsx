const OAUTH_POPUP_WIDTH = 500;
const OAUTH_POPUP_HEIGHT = 600;

const openOAuthPopup = () => {
  const left = window.screenX + (window.outerWidth - OAUTH_POPUP_WIDTH) / 2;
  const top = window.screenY + (window.outerHeight - OAUTH_POPUP_HEIGHT) / 2;
  window.open(
    `${import.meta.env.VITE_OAUTH_URL}/oauth2/authorization/google`,  // 또는 kakao, naver 등
    "_blank",
    `width=${OAUTH_POPUP_WIDTH},height=${OAUTH_POPUP_HEIGHT},left=${left},top=${top}`
  );
};

const OAuthLoginButton: React.FC = () => {
  return <button onClick={openOAuthPopup}>Google로 로그인</button>;
};

export default OAuthLoginButton;
