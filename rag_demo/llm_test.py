# -*- coding: utf-8 -*-
"""
Gemma-2-9B-it (GGUF, Q4_K_M) 온디맨드 요약기 - 단일 파일
- llama-cpp-python 필요
- Gemma chat_format 적용 (system 없음)
- 한국어 2줄 불릿 요약, 길이/포맷 가드 + 견고한 후처리
- CLI / 모듈 겸용

사용:
  python gemma_summary.py -t "요약할 텍스트"
  echo "텍스트" | python gemma_summary.py --stdin
환경변수:
  MODEL_PATH=C:\llm\gguf\gemma-2-9b-it.Q4_K_M.gguf
  N_CTX=4096  N_BATCH=512  TEMP=0.2  TOP_P=0.9  MAX_NEW=120
"""

import os
import sys
import time
import re
import argparse
from typing import Optional, List

try:
    from llama_cpp import Llama
except Exception as e:
    print("llama-cpp-python 미설치 또는 로드 실패:", e, file=sys.stderr)
    sys.exit(1)

# ===== 설정 =====
DEF_MODEL = r"C:\llm\gguf\gemma-2-9b-it.Q4_K_M.gguf"
MODEL_PATH = os.getenv("MODEL_PATH", DEF_MODEL)
N_CTX      = int(os.getenv("N_CTX", "4096"))
N_BATCH    = int(os.getenv("N_BATCH", "512"))
TEMP       = float(os.getenv("TEMP", "0.2"))
TOP_P      = float(os.getenv("TOP_P", "0.9"))
MAX_NEW    = int(os.getenv("MAX_NEW", "120"))

# Gemma는 system 롤 없음 → 지시를 user에 포함
INSTR_KR = (
    "너는 RAG 요약기다. 한국어로만 답하라. "
    "항상 정확한 두 개의 매우 짧은 불릿을 출력하라(각 15단어 이하). "
    "서문/후기/추가 설명/코드블록/마크업 금지. 오직 두 줄 불릿만."
)

_llm_singleton: Optional[Llama] = None


def load_llm() -> Llama:
    """LLM 싱글톤 로더 (초기 로드만 느리고, 이후 재사용)."""
    global _llm_singleton
    if _llm_singleton is not None:
        return _llm_singleton

    t0 = time.time()
    _llm_singleton = Llama(
        model_path=MODEL_PATH,
        n_ctx=N_CTX,
        n_gpu_layers=-1,       # 가능한 한 GPU에 올림
        n_batch=N_BATCH,
        seed=0,
        verbose=False,
        chat_format="gemma",   # Gemma 템플릿 명시
    )
    t1 = time.time()
    print(f"[LLM] Loaded in {t1 - t0:.2f}s — {MODEL_PATH}", file=sys.stderr)
    return _llm_singleton


def _postprocess_to_two_bullets(text: str) -> str:
    """
    모델 출력을 '한국어 2줄 불릿'으로 정규화.
    - 선행 불릿기호/공백 제거 -> 2줄만 채택
    - 빈 응답/영어 혼입 시에도 최대한 안전하게 정리
    """
    # 줄 단위 분리
    raw_lines = [l.strip() for l in text.splitlines() if l.strip()]
    # 마크다운/불릿 기호 제거
    lines = [re.sub(r'^[\-\•\●\*\u2022\+\d\.\)\(]+\s*', '', l).strip() for l in raw_lines]
    # 너무 긴 줄은 간단히 자름(실전 방지)
    lines = [l[:180] for l in lines if l]
    if not lines:
        return "• 요약 생성 실패\n• 입력을 줄이거나 다시 시도하세요"

    # 상위 두 줄만
    lines = lines[:2]
    # 2줄 미만이면 채움
    if len(lines) == 1:
        lines.append("두 번째 불릿을 생성할 수 없습니다")

    # 앞에 통일된 불릿 기호 붙이기
    return f"• {lines[0]}\n• {lines[1]}"


def gen_summary_kr(text: str, *, temp: float = TEMP, top_p: float = TOP_P, max_new_tokens: int = MAX_NEW) -> str:
    """
    한국어 2줄 불릿 요약 생성. 실패 시 최대한 그럴듯하게 포맷 유지.
    """
    if not text or not text.strip():
        return "• 빈 입력입니다\n• 내용을 제공해 주세요"

    llm = load_llm()

    # Gemma는 system 미지원 → 지시를 user에 합침
    prompt_user = (
        f"{INSTR_KR}\n\n"
        f"{text.strip()[:1200]}\n"
        f"두 줄 불릿만 반환하라."
    )

    try:
        t0 = time.time()
        out = llm.create_chat_completion(
            messages=[{"role": "user", "content": prompt_user}],
            temperature=temp,
            top_p=top_p,
            max_tokens=max_new_tokens,
            # stop=["<|eot_id|>"]  # 필요시 활성화
        )
        dt = time.time() - t0
        print(f"[LLM] gen {dt:.2f}s", file=sys.stderr)

        ans = out["choices"][0]["message"]["content"]
        return _postprocess_to_two_bullets(ans)
    except Exception as e:
        # 안전장치: 실패 시 입력 앞부분으로 임시 요약 대체
        print(f"[LLM] ERROR: {e}", file=sys.stderr)
        fallback = text.strip().splitlines()[0][:160] if text.strip() else "요약 실패"
        return _postprocess_to_two_bullets(fallback)


# ========== CLI ==========

def _read_stdin() -> str:
    try:
        data = sys.stdin.read()
        return data
    except Exception:
        return ""


def main():
    parser = argparse.ArgumentParser(description="Gemma-2-9B-it Q4_K_M 한국어 2줄 요약기 (llama-cpp)")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("-t", "--text", type=str, help="요약할 텍스트 문자열")
    src.add_argument("--stdin", action="store_true", help="표준입력으로 텍스트 읽기")

    args = parser.parse_args()

    if args.stdin:
        text = _read_stdin()
    else:
        text = args.text or ""

    summary = gen_summary_kr(text)
    print(summary)


if __name__ == "__main__":
    main()
