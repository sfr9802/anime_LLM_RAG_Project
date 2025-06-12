import openai
import os

openai.api_key = os.getenv("openai_api_key")

async def ask_gpt(prompt : str, model="gpt-3.5-turbo"):
    
    response = openai.ChatCompetion.create(
        model = model,
        message=[{"role" : "user", "content" : prompt}],
        temperature=0.7,
        max_token=512
        
    )
    return response["choices"][0]["message"]["content"]
    
    return f"[MOCK] '{question}' 에 대한 답변 : ... (based on {len(docs)} docs)"
    