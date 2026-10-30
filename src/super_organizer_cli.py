from sqlmodel import Session, create_engine

from src.models import PermissionKey, UserState

cmd = input("[mk / rm]: ")
tg_id = int(input("TG ID: "))

engine = create_engine("sqlite:///amongus_bot.db")

with Session(engine) as session:
    user = session.get(UserState, tg_id)

    if cmd == "mk":
        user.permission_key = PermissionKey.organizer
        
    elif cmd == "rm":
        user.permission_key = PermissionKey.user

    session.add(user)
    session.commit()
    print(f"{user.tg_id}: {user.permission_key.value}")