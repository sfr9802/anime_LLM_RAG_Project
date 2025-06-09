
async def gpt_answer(question:str, docs:list):
    context = "\n".join(doc["text"] for doc in docs)
    # TODO: huggingFace, GPT call
    return f"[MOCK] '{question}' 에 대한 답변 : ... (based on {len(docs)} docs)"
    