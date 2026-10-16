from pydantic import BaseModel, ConfigDict

from src.domain.enums import Category


class NewStoreDTO(BaseModel):
    user_id: int
    store_key: str
    name: str


class StoreDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: int
    user_id: int
    store_key: str
    name: str


class NewStoreProductDTO(BaseModel):
    user_id: int
    store_id: int
    product_key: str
    name: str
    name_raw: str
    # Plain strings: the database CHECK is the single source of truth for valid values.
    category: str = Category.OTHER.value
    unit: str = "pcs"


class StoreProductDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: int
    user_id: int
    store_id: int
    product_key: str
    name: str
    name_raw: str
    category: str
    unit: str
