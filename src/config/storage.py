from pathlib import Path

from pydantic import BaseModel


class StorageConfig(BaseModel):
    receipts_dir: Path = Path("data/receipts")
