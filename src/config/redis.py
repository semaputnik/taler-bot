from pydantic import BaseModel, RedisDsn


class RedisConfig(BaseModel):
    url: RedisDsn = RedisDsn("redis://localhost:6390/0")
