import datetime
import uuid
from datetime import timezone
from enum import Enum

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel, Field, Relationship


class PermissionKey(str, Enum):
    organizer = "organizer"
    participant = "participant"
    user = "user"


class KillCaseStatus(str, Enum):
    approved = "approved"
    rejected = "rejected"
    pending = "pending"
    disputed = "disputed"
    game_ended = "game_ended"


class GameStatus(str, Enum):
    InvitationsPending = "invitations_pending"
    GameIsGoing = "game_is_going"
    Finalized = "finalized"


class GameAndUsers(SQLModel, table=True):
    user_id: int = Field(foreign_key="userstate.tg_id", nullable=False, primary_key=True)
    game_id: uuid.UUID = Field(foreign_key="gamestate.id", nullable=False, primary_key=True)


class UserState(SQLModel, table=True):
    tg_id: int = Field(primary_key=True, nullable=False, index=True)
    permission_key: PermissionKey = PermissionKey.user
    tg_name: str = Field(nullable=False)
    killed: bool = Field(default=False)
    full_name: str = Field(nullable=False)
    group: str = Field(nullable=False)

    form_accepted: bool | None = Field(default=None, nullable=True)
    reject_reason: str | None = Field(default=None, nullable=True)
    games: list["GameState"] = Relationship(back_populates="playing_users", link_model=GameAndUsers)




class KillCase(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    from_user_id: int = Field(foreign_key="userstate.tg_id", nullable=False)
    status: KillCaseStatus = Field(nullable=False, default=KillCaseStatus.pending)
    evidence_id: str = Field(nullable=False)
    sent_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC))
    user_victim_id: uuid.UUID = Field(foreign_key="uservictim.id", nullable=False)
    approved_at: datetime.datetime | None


class GameState(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    status: GameStatus = GameStatus.InvitationsPending
    game_name: str
    game_has_ended: bool | None = None
    started_at: datetime.datetime | None = None
    ended_at: datetime.datetime | None = None
    forced_ending: bool | None = None
    playing_users: list["UserState"] = Relationship(back_populates="games", link_model=GameAndUsers)

    @staticmethod
    async def close_the_game(session: AsyncSession):
        game = await GameState.current_game(session)

        game.status = GameStatus.Finalized
        game.ended_at = datetime.datetime.now(timezone.utc)
        game.forced_ending = True
        game.game_has_ended = True

        query = update(UserVictim).where(UserVictim.game_id == game.id).values(active=False)

        await session.execute(query)

        session.add(game)

        return game

    @staticmethod
    async def current_game(session: AsyncSession) -> GameState:
        stmt = select(GameState).where(GameState.status != GameStatus.Finalized)
        return (await session.scalars(stmt)).first()



class UserVictim(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: int = Field(foreign_key="userstate.tg_id", nullable=False)
    victim_id: int = Field(foreign_key="userstate.tg_id", nullable=False)
    active: bool = Field(default=True, index=True)
    game_id: uuid.UUID = Field(foreign_key="gamestate.id", nullable=False)
    created_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC))