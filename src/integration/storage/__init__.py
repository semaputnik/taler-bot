from src.integration.storage.interface import PhotoStorage, StorageError
from src.integration.storage.local import LocalPhotoStorage

__all__ = ["LocalPhotoStorage", "PhotoStorage", "StorageError"]
