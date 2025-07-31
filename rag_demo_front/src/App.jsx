import React, { useEffect, useState } from 'react';
import axios from 'axios';

function App() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [profile, setProfile] = useState(null);
  const [message, setMessage] = useState(null);
  const [token, setToken] = useState(localStorage.getItem('token') || '');

  const [query, setQuery] = useState('');
  const [ragAnswer, setRagAnswer] = useState(null);

  // ✅ accessToken을 Axios 전역에 적용
  useEffect(() => {
    if (token) {
      axios.defaults.headers.common['Authorization'] = `Bearer ${token}`;
      fetchProfile();
    } else {
      delete axios.defaults.headers.common['Authorization'];
    }
  }, [token]);

  // ✅ postMessage 방식으로 popup에서 전달된 토큰 수신
  useEffect(() => {
    const handler = (event) => {
      if (!event.origin.startsWith('http://localhost:3000')) return;
      const { accessToken } = event.data;
      if (accessToken) {
        localStorage.setItem('token', accessToken);
        setToken(accessToken);
        setMessage('OAuth 로그인 성공');
      }
    };
    window.addEventListener('message', handler);
    return () => window.removeEventListener('message', handler);
  }, []);

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

  // ✅ popup 방식으로 OAuth 로그인 시도
  const handleOAuthLogin = () => {
    const popup = window.open(
      'http://localhost:8080/oauth2/authorization/google',
      'oauth2Login',
      'width=600,height=700'
    );

    // 로그인 실패 또는 창 닫힘 대비 (선택사항)
    const timer = setInterval(() => {
      if (popup && popup.closed) {
        clearInterval(timer);
        setMessage('OAuth 창이 닫혔습니다');
      }
    }, 1000);
  };

  const handleLogout = () => {
    localStorage.removeItem('token');
    setToken('');
    setProfile(null);
    setMessage('로그아웃됨');
  };

  const handleRagQuery = () => {
    if (!query.trim()) return;

    axios.post('/api/proxy', {
      targetUrl: 'http://localhost:8000/rag/query',
      query: query
    })
      .then(res => {
        setRagAnswer(res.data.answer || JSON.stringify(res.data));
        setMessage('질의 성공');
      })
      .catch(err => {
        console.error(err);
        setMessage('질의 실패');
        setRagAnswer(null);
      });
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

      <div style={{ marginTop: '30px' }}>
        <h2>RAG 질의</h2>
        <input
          type="text"
          placeholder="예: 이재명 정부의 부동산 정책"
          value={query}
          onChange={e => setQuery(e.target.value)}
          style={{ width: '60%', marginRight: '8px' }}
        />
        <button onClick={handleRagQuery}>질의하기</button>

        {ragAnswer && (
          <div style={{ marginTop: '20px' }}>
            <h3>📘 LLM 응답</h3>
            <pre style={{ whiteSpace: 'pre-wrap', backgroundColor: '#f5f5f5', padding: '10px' }}>
              {ragAnswer}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}

export default App;
