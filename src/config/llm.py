from pydantic import BaseModel, SecretStr


class LLMConfig(BaseModel):
    model: str = "openai:gpt-6-luna"
    api_key: SecretStr
    timeout_s: float = 120
