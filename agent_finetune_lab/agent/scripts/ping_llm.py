import asyncio, os, httpx

BASE = os.getenv("LLM_BASE_URL", "http://127.0.0.1:8000/v1")
PATH = "chat/completions" if BASE.rstrip("/").endswith("/v1") else "/v1/chat/completions"
MODEL = os.getenv("LLM_MODEL", "gemma-2-9b-it")

async def main():
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as cli:
        r = await cli.post(PATH, json={"model": MODEL, "messages":[{"role":"user","content":"Say OK"}], "max_tokens":8})
        r.raise_for_status(); print(r.json()["choices"][0]["message"]["content"])

if __name__ == "__main__":
    asyncio.run(main())
