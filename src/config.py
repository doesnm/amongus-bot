from functools import lru_cache
from typing import Annotated, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode


class Config(BaseSettings, case_sensitive=False):
    bot_token: str = "placeholder"
    org_chat_id: int
    root_org_ids: Annotated[list[int], NoDecode] = []
    manual_form_approval: bool = True

    environment_profile: Literal["DEV", "TEST", "PROD"] = "DEV"

    @field_validator("root_org_ids", mode="before")
    @classmethod
    def parse_root_org_ids(cls, value: object) -> object:
        if isinstance(value, int):
            return [value]
        if isinstance(value, str):
            return [int(part) for part in value.split(",") if part.strip()]
        return value


@lru_cache
def get_config() -> Config:
    return Config()
