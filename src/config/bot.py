from pydantic import BaseModel, SecretStr


class BotConfig(BaseModel):
    token: SecretStr
