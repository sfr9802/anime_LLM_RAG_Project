import axios from '@/libs/axios';
import type { ChatMessage } from '../types/Message'; // ✅ 타입 전용 import


export async function sendMessage(messages: ChatMessage[]) {
  const res = await axios.post('/api/chat', { messages });
  return res.data; // { reply: string, sources?: [...] }
}
