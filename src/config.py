from typing import Literal

from pydantic_settings import BaseSettings


class Config(BaseSettings, case_sensitive=False):
    bot_token: str = "placeholder"

    environment_profile: Literal["DEV", "TEST", "PROD"] = "DEV"
