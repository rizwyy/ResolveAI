import time

from sqlalchemy import select

from .db import SessionLocal
from .models import Turn
from .services import process_turn


def run_once() -> int:
    with SessionLocal() as db:
        turns = list(db.scalars(select(Turn).where(Turn.status == "queued").order_by(Turn.created_at).limit(10)))
        for turn in turns:
            process_turn(db, turn)
        return len(turns)


def main() -> None:
    while True:
        processed = run_once()
        time.sleep(0.25 if processed else 1.0)


if __name__ == "__main__":
    main()
