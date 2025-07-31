import type { ChatMessage } from '../types/Message';
import './ChatBubble.css';

interface Props {
  readonly message: ChatMessage;
}

export default function ChatBubble({ message }: Props) {
  const isUser = message.role === 'user';

  return (
    <div className={`chat-bubble-wrapper ${isUser ? 'right' : 'left'}`}>
      <div className={`chat-bubble ${isUser ? 'user' : 'assistant'}`}>
        {message.content}
      </div>
    </div>
  );
}
