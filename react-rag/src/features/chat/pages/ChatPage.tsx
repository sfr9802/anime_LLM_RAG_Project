import { useState, useEffect, useRef } from 'react';
import type { ChatMessage } from '../types/Message';
import ChatBubble from '../components/ChatBubble';
import ChatInput from '../components/ChatInput';
import './ChatPage.css'; // 스타일 분리

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const scrollRef = useRef<HTMLDivElement | null>(null); // ⬅️ 스크롤 타겟

  const handleSend = (text: string) => {
    const userMsg: ChatMessage = { role: 'user', content: text };
    const aiMsg: ChatMessage = { role: 'assistant', content: `🤖 이것은 ${text}에 대한 응답입니다.` };
    setMessages(prev => [...prev, userMsg, aiMsg]);
  };

  // ✅ 메시지 추가 시 스크롤 아래로
  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  return (
    <div className="chat-container">
      <div className="chat-messages">
        {messages.map((msg, i) => (
          <ChatBubble key={i} message={msg} />
        ))}
        <div ref={scrollRef} /> {/* 자동 스크롤 타겟 */}
      </div>

      <div className="chat-input-wrapper">
        <ChatInput onSend={handleSend} />
      </div>
    </div>
  );
}
