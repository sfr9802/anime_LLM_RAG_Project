import React, { useEffect, useState } from 'react';
import axios from 'axios';

function App() {
  const [users, setUsers] = useState([]);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [message, setMessage] = useState(null);  // ✅ 성공/실패 메시지

  // 사용자 목록 조회
  const fetchUsers = () => {
    axios.get('/api/users/browse')
      .then(res => {
        if (res.data.success) {
          setUsers(res.data.data);
        } else {
          setMessage(res.data.data);
        }
      })
      .catch(err => {
        console.error(err);
        setMessage('사용자 목록을 불러오는 중 오류 발생');
      });
  };

  useEffect(() => {
    fetchUsers();
  }, []);

  // 회원 등록
  const handleRegister = () => {
    axios.post('/api/users/register', {
      username,
      password
    })
    .then(res => {
      if (res.data.success) {
        setMessage('등록 성공!');
        setUsername('');
        setPassword('');
        fetchUsers();  // ✅ 목록 갱신
      } else {
        setMessage(res.data.data);  // 오류 메시지 출력
      }
    })
    .catch(err => {
      console.error(err);
      setMessage('등록 중 오류 발생');
    });
  };

  return (
    <div style={{ padding: '20px' }}>
      <h1>사용자 등록</h1>
      <input
        type="text"
        placeholder="Username"
        value={username}
        onChange={e => setUsername(e.target.value)}
        style={{ marginRight: '8px' }}
      />
      <input
        type="password"
        placeholder="Password"
        value={password}
        onChange={e => setPassword(e.target.value)}
        style={{ marginRight: '8px' }}
      />
      <button onClick={handleRegister}>등록</button>

      {message && <p style={{ color: 'crimson', marginTop: '10px' }}>{message}</p>}

      <h2>사용자 목록</h2>
      <ul>
        {users.map((user, index) => (
          <li key={index}>{user.username}</li>
        ))}
      </ul>
    </div>
  );
}

export default App;
