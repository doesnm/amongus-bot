from pydantic_settings import BaseSettings


class Config(BaseSettings, case_sensitive=False):
    bot_token: str

    envoirment_profile: "DEV" | ""
