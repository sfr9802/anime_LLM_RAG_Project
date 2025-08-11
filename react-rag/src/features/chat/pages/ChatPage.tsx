import { useState, useEffect, useRef } from 'react';
import type { ChatMessage } from '../types/Message';
import ChatBubble from '../components/ChatBubble';
import ChatInput from '../components/ChatInput';
import { sendMessage } from '../services/chatApi';
import './ChatPage.css';

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const handleSend = async (text: string) => {
    const userMsg: ChatMessage = { role: 'user', content: text };
    const newMessages = [...messages, userMsg]; // ✅ 최신 상태 반영
    setMessages(newMessages);

    setLoading(true);
    try {
      const { reply, sources } = await sendMessage(newMessages);
      const aiMsg: ChatMessage = {
        role: 'assistant',
        content: reply ?? '🤖 응답이 비어 있습니다.',
      };
      setMessages(prev => [...prev, aiMsg]);

      // ✅ sources 처리하려면 아래처럼 별도 저장 or 확장 필요
      if (sources) {
        console.log('출처:', sources); // or setSources()
      }

    } catch (err) {
      console.error('백엔드 요청 실패:', err);
      const errMsg: ChatMessage = {
        role: 'assistant',
        content: '⚠️ 서버 응답에 실패했습니다.',
      };
      setMessages(prev => [...prev, errMsg]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  return (
    <div className="chat-container">
      <div className="chat-messages">
        {messages.map((msg, i) => (
          <ChatBubble key={i} message={msg} />
        ))}
        <div ref={scrollRef} />
      </div>

      <div className="chat-input-wrapper">
        <ChatInput onSend={handleSend} disabled={loading} /> {/* ✅ loading 방지 */}
      </div>
    </div>
  );
}
