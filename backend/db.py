from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from config import DATABASE_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True)  # pool_pre_ping: survive DB restarts
SessionLocal = sessionmaker(engine)


class Base(DeclarativeBase):
    pass


if __name__ == "__main__":
    # smoke check: prove the app reaches the DB the env describes. Fails loudly if not.
    with engine.connect() as conn:
        print("connected:", conn.execute(text("SELECT version()")).scalar_one())
        print(
            "extensions available:",
            conn.execute(
                text("SELECT string_agg(name, ', ') FROM pg_available_extensions WHERE name IN ('pg_trgm','fuzzystrmatch')")
            ).scalar_one(),
        )
