from huggingface_hub import hf_hub_download

repo_id = "bartowski/gemma-2-9b-it-GGUF"
filename = "gemma-2-9b-it.Q4_K_M.gguf"

p = hf_hub_download(repo_id=repo_id, filename=filename, local_dir="C:/llm/gguf")
print("Saved:", p)
