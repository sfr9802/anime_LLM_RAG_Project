from pydantic import BaseSettings, Field

class Settings(BaseSettings):
    # LLM
    llm_base_url: str = Field(..., env="LLM_BASE_URL")     # 예: http://llm:8080/v1
    llm_model: str    = Field(..., env="LLM_MODEL")        # 예: gemma-2-9b-it
    llm_timeout: float = Field(60.0, env="LLM_TIMEOUT")
    llm_api_key: str | None = Field(None, env="LLM_API_KEY")

    # Agent
    temperature: float = Field(0.2, env="AGENT_TEMPERATURE")
    max_steps: int     = Field(6, env="AGENT_MAX_STEPS")

    class Config:
        env_file = ".env"
        extra = "ignore"
