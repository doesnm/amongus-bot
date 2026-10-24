import datetime
import uuid
from enum import Enum

from sqlmodel import SQLModel, Field


class PermissionKey(str, Enum):
    organizer = "organizer"
    participant = "participant"
    user = "user"


class KillCaseStatus(str, Enum):
    approved = "approved"
    rejected = "rejected"
    pending = "pending"
    disputed = "disputed"


class GameStatus(str, Enum):
    InvitationsPending = "invitations_pending"
    GameIsGoing = "game_is_going"
    Finalized = "finalized"


class UserState(SQLModel, table=True):
    tg_id: int = Field(primary_key=True, nullable=False, index=True)
    permission_key: PermissionKey = PermissionKey.user
    tg_name: str = Field(nullable=False)
    killed: bool = Field(default=False)
    full_name: str = Field(nullable=False)
    group: str = Field(nullable=False)


class UserVictim(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: int = Field(foreign_key="userstate.tg_id", nullable=False)
    victim_id: int = Field(foreign_key="userstate.tg_id", nullable=False)
    active: bool = Field(default=True, index=True)
    created_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC))


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
    game_has_ended: bool = False
    started_at: datetime.datetime | None = None
    ended_at: datetime.datetime | None = None
    forced_ending: bool | None = None
