// src/features/chat/services/chatApi.ts
import axios from "@/libs/axios";
import type { ChatMessage } from "../types/Message";

export async function sendMessage(messages: ChatMessage[]) {
  // 대화 내 마지막 user 메시지만 FastAPI에 보냄
  const lastUser = [...messages].reverse().find(m => m.role === "user");
  const question = (lastUser?.content ?? "").trim();

  const { data } = await axios.post("/api/proxy/ask-v2", {
    question,
    path: "/rag/ask",       // FastAPI 라우트 (기본이면 유지)
    // 필요하면 파라미터 추가:
    // k: 6, candidate_k: null, use_mmr: true, lam: 0.5, max_tokens: 512, temperature: 0.2, preview_chars: 600
  });

  // ProxyResponseDto { question, answer } 대응
  return {
    reply: data?.answer ?? String(data),
    // 백엔드에서 sources를 넣어주면 여기서 꺼내 쓰면 됨
    sources: data?.sources ?? [],
  };
}
