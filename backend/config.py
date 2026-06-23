import os

from dotenv import load_dotenv

load_dotenv()  # ponytail: .env is the single source of truth; URL derived, not stored

DATABASE_URL = (
    f"postgresql+psycopg://{os.environ['POSTGRES_USER']}:"
    f"{os.environ['POSTGRES_PASSWORD']}@{os.environ['POSTGRES_HOST']}:"
    f"{os.environ['POSTGRES_PORT']}/{os.environ['POSTGRES_DB']}"
)
