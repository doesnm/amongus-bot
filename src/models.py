from sqlmodel import SQLModel, Field


class UserState(SQLModel, table=True):
    tg_id: int = Field(primary_key=True)