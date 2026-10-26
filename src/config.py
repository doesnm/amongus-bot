from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings


class Config(BaseSettings, case_sensitive=False):
    bot_token: str = "placeholder"
    org_chat_id: int
    root_org_id: int | None = None
    manual_form_approval: bool = True

    environment_profile: Literal["DEV", "TEST", "PROD"] = "DEV"


@lru_cache
def get_config() -> Config:
    return Config()
