import os

from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv()

engine = create_engine(os.environ["DATABASE_URL"])


def get_connection():
    return engine.connect()


def get_db_dependency():
    """FastAPI dependency wrapper around get_connection().

    Exists so routes can use Depends(get_db_dependency) and tests can
    replace it via app.dependency_overrides without touching
    get_connection() or any existing route.
    """
    with get_connection() as conn:
        yield conn
