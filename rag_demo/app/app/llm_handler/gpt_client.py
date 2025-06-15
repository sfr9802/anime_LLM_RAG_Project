import openai
import os

openai.api_key = os.getenv("openai_api_key")


def ask_gpt(prompt: str, model: str = "gpt-3.5-turbo") -> str:
    """Call OpenAI's chat completion API and return the assistant reply."""
    response = openai.ChatCompletion.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=512,
    )
    return response["choices"][0]["message"]["content"]
    