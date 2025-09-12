import { useState } from 'react';
import './ChatInput.css';

interface Props {
  onSend: (message: string) => void;
  disabled?: boolean;
}

export default function ChatInput({ onSend, disabled = false }: Props) {
  const [input, setInput] = useState('');

  const handleSubmit = () => {
    if (!input.trim() || disabled) return;
    onSend(input);
    setInput('');
  };

  return (
    <div className="chat-input">
      <div className="input-container">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') handleSubmit(); // disabled 방어는 handleSubmit에 있음
          }}
          className="input-box"
          placeholder="질문을 입력하세요..."
          disabled={disabled} // 입력 자체 비활성화
        />
        <button
          onClick={handleSubmit}
          className="send-button"
          disabled={disabled}
        >
          전송
        </button>
      </div>
    </div>
  );
}
