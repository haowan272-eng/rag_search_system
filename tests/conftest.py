"""共享知识库服务测试夹具。"""
import os
import sys
from unittest.mock import MagicMock

import bcrypt
import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# 必须在导入配置前设置；load_dotenv 不会覆盖已有环境变量。
os.environ["APP_ENV"] = "test"
os.environ["SECRET_KEY"] = "test-access-secret-key-at-least-32-bytes"
os.environ["REFRESH_SECRET_KEY"] = "test-refresh-secret-key-at-least-32-bytes"

from app.core.config import ALGORITHM, SECRET_KEY
from app.core.database import Base, get_db
from app.models import Document, KnowledgeBase, KnowledgeBaseMember, User


@pytest.fixture(scope="session")
def engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session(engine):
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        # SQLite may commit the outer transaction when releasing a savepoint.
        # Clear tables in reverse FK order so tests stay isolated after commits.
        with engine.begin() as connection:
            for table in reversed(Base.metadata.sorted_tables):
                connection.execute(table.delete())


def _auth_user(db, username: str):
    user = User(
        username=username,
        password=bcrypt.hashpw(b"testpass", bcrypt.gensalt()).decode(),
    )
    db.add(user)
    db.flush()
    token = jwt.encode({"sub": username}, SECRET_KEY, algorithm=ALGORITHM)
    return user, {"Authorization": f"Bearer {token}"}


@pytest.fixture
def auth_user(db_session):
    return _auth_user(db_session, "user_a")


@pytest.fixture
def auth_user2(db_session):
    return _auth_user(db_session, "user_b")


@pytest.fixture
def app(db_session):
    from app.main import app

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield app
    app.dependency_overrides.clear()


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def factory():
    class Factory:
        @staticmethod
        def document(db, user_id: int, **overrides):
            values = {
                "user_id": user_id,
                "original_file_name": "shared.txt",
                "file_name": "shared.txt",
                "file_path": "shared.txt",
                "status": "indexed",
                "source_retained": True,
            }
            values.update(overrides)
            document = Document(**values)
            db.add(document)
            db.flush()
            return document

        @staticmethod
        def knowledge_base(db, owner_id: int, name: str = "共享知识库"):
            kb = KnowledgeBase(name=name, created_by=owner_id)
            db.add(kb)
            db.flush()
            db.add(KnowledgeBaseMember(kb_id=kb.id, user_id=owner_id, role="owner"))
            db.flush()
            return kb

    return Factory()


@pytest.fixture
def mock_qdrant():
    client = MagicMock()
    client.collection_exists.return_value = True
    info = MagicMock()
    info.config.params.vectors.size = 1024
    client.get_collection.return_value = info
    result = MagicMock()
    result.points = []
    client.query_points.return_value = result
    client.count.return_value = MagicMock(count=0)
    return client


@pytest.fixture
def mock_redis():
    client = MagicMock()
    client.set.return_value = True
    pipeline = MagicMock()
    pipeline.__enter__.return_value = pipeline
    pipeline.__exit__.return_value = False
    client.pipeline.return_value = pipeline
    return client
