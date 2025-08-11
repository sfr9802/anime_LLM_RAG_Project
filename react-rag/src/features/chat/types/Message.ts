export type ChatRole = 'user' | 'assistant';

export interface ChatMessage {
  role: ChatRole;
  content: string;
  sources?: SourceInfo[]; // 👈 선택적 필드로 추가
}

export interface SourceInfo {
  title: string;
  url?: string;
  snippet?: string;
}
