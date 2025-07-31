// /src/pages/OAuthSuccessPopup.jsx
import { useEffect } from 'react';
import axios from 'axios';

function OAuthSuccessPopup() {
  useEffect(() => {
    const fetchToken = async () => {
      try {
        const res = await axios.get('/api/oauth/token');
        const accessToken = res.data.accessToken;
        if (accessToken) {
          window.opener.postMessage({ accessToken }, 'http://localhost:3000');
          window.close();
        }
      } catch (err) {
        console.error('토큰 전달 실패', err);
      }
    };

    fetchToken();
  }, []);

  return <p>로그인 처리 중...</p>;
}

export default OAuthSuccessPopup;
