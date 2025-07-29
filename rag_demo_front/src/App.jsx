import React, { useEffect, useState } from 'react';
import axios from 'axios';

function App() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [profile, setProfile] = useState(null);
  const [message, setMessage] = useState(null);
  const [token, setToken] = useState(localStorage.getItem('token') || '');

  // 토큰을 매 요청마다 넣도록 설정 (authAxios 안 쓰고 global 방식)
  useEffect(() => {
    if (token) {
      axios.defaults.headers.common['Authorization'] = `Bearer ${token}`;
    } else {
      delete axios.defaults.headers.common['Authorization'];
    }
  }, [token]);

  // 쿼리 파라미터에서 토큰 추출
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const tokenFromOAuth = params.get('token');

    if (tokenFromOAuth && !token) {
      localStorage.setItem('token', tokenFromOAuth);
      setToken(tokenFromOAuth);
      setMessage('OAuth 로그인 성공');
      window.history.replaceState({}, document.title, window.location.pathname); // URL 정리
    } else if (token) {
      fetchProfile();
    }
  }, [token]);

  const fetchProfile = () => {
    axios.get('/api/users/me')
      .then(res => {
        setProfile(res.data);
        setMessage('프로필 조회 성공');
      })
      .catch(err => {
        console.error(err);
        setMessage('프로필 조회 실패');
      });
  };

  const handleJwtLogin = () => {
    axios.post('/api/users/login', { email, password })
      .then(res => {
        if (res.data.token) {
          localStorage.setItem('token', res.data.token);
          setToken(res.data.token);
          setMessage('로그인 성공');
          setEmail('');
          setPassword('');
        } else {
          setMessage('JWT 응답 없음');
        }
      })
      .catch(err => {
        console.error(err);
        setMessage('로그인 실패');
      });
  };

  const handleOAuthLogin = () => {
    window.location.href = 'http://localhost:8080/oauth2/authorization/google';
  };

  const handleLogout = () => {
    localStorage.removeItem('token');
    setToken('');
    setProfile(null);
    setMessage('로그아웃됨');
  };

  return (
    <div style={{ padding: '20px' }}>
      <h1>사용자 인증</h1>

      <div style={{ marginBottom: '10px' }}>
        <input
          type="text"
          placeholder="Email"
          value={email}
          onChange={e => setEmail(e.target.value)}
          style={{ marginRight: '8px' }}
        />
        <input
          type="password"
          placeholder="Password"
          value={password}
          onChange={e => setPassword(e.target.value)}
          style={{ marginRight: '8px' }}
        />
      </div>

      <button onClick={handleJwtLogin} style={{ marginRight: '8px' }}>JWT 로그인</button>
      <button onClick={handleOAuthLogin} style={{ marginRight: '8px' }}>Google 로그인</button>
      <button onClick={handleLogout}>로그아웃</button>

      {message && <p style={{ color: 'crimson', marginTop: '10px' }}>{message}</p>}

      {profile && (
        <div style={{ marginTop: '20px' }}>
          <h2>내 프로필</h2>
          <p><strong>닉네임:</strong> {profile.nickname}</p>
          <p><strong>이메일:</strong> {profile.email}</p>
          <p><strong>역할:</strong> {profile.role}</p>
        </div>
      )}
    </div>
  );
}

export default App;
