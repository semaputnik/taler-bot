from pydantic import BaseModel, PostgresDsn


class DatabaseConfig(BaseModel):
    url: PostgresDsn
