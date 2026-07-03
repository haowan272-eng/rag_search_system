"""PostgreSQL Schema 迁移。

项目不依赖额外迁移服务。FastAPI 在 create_all 后调用 run_migrations，
为已有数据库补齐 ORM 新增字段。PostgreSQL advisory lock 确保多实例
启动时只有一个实例执行迁移。
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

MIGRATION_LOCK_ID = 2026061901


@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    statements: tuple[str, ...]


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version="20260619_01",
        name="multimodal_document_chunks",
        statements=(
            "ALTER TABLE documents_chunks ADD COLUMN IF NOT EXISTS embedding_content TEXT",
            (
                "ALTER TABLE documents_chunks ADD COLUMN IF NOT EXISTS modality "
                "VARCHAR(16) NOT NULL DEFAULT 'text'"
            ),
            "ALTER TABLE documents_chunks ADD COLUMN IF NOT EXISTS page_start INTEGER",
            "ALTER TABLE documents_chunks ADD COLUMN IF NOT EXISTS page_end INTEGER",
            "ALTER TABLE documents_chunks ADD COLUMN IF NOT EXISTS metadata_json TEXT",
            (
                "CREATE INDEX IF NOT EXISTS ix_documents_chunks_document_id "
                "ON documents_chunks (document_id)"
            ),
            (
                "CREATE INDEX IF NOT EXISTS ix_documents_chunks_modality "
                "ON documents_chunks (modality)"
            ),
        ),
    ),
    Migration(
        version="20260619_02",
        name="chunk_embeddings_nullable_vector",
        statements=(
            "ALTER TABLE chunk_embeddings ALTER COLUMN embedding DROP NOT NULL",
        ),
    ),
    Migration(
        version="20260620_01",
        name="knowledge_base_rbac",
        statements=(
            """CREATE TABLE IF NOT EXISTS knowledge_bases (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                chunk_config TEXT,
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )""",
            """CREATE TABLE IF NOT EXISTS knowledge_base_members (
                id SERIAL PRIMARY KEY,
                kb_id INTEGER NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                role VARCHAR(20) NOT NULL DEFAULT 'viewer',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_kb_member UNIQUE (kb_id, user_id)
            )""",
            "CREATE INDEX IF NOT EXISTS ix_knowledge_bases_created_by ON knowledge_bases (created_by)",
            "CREATE INDEX IF NOT EXISTS ix_knowledge_base_members_kb_id ON knowledge_base_members (kb_id)",
            "CREATE INDEX IF NOT EXISTS ix_knowledge_base_members_user_id ON knowledge_base_members (user_id)",
            "ALTER TABLE documents ADD COLUMN IF NOT EXISTS kb_id INTEGER",
            "CREATE INDEX IF NOT EXISTS ix_documents_kb_id ON documents (kb_id)",
            "ALTER TABLE documents ADD COLUMN IF NOT EXISTS pipeline_version VARCHAR",
        ),
    ),
    Migration(
        version="20260620_02",
        name="detach_shared_documents_from_conversations",
        statements=(
            "ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_conversation_id_fkey",
            (
                "ALTER TABLE document_structured_fields DROP CONSTRAINT IF EXISTS "
                "document_structured_fields_conversation_id_fkey"
            ),
        ),
    ),
    Migration(
        version="20260620_03",
        name="private_rag_conversations",
        statements=(
            """CREATE TABLE IF NOT EXISTS rag_conversations (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                kb_id INTEGER REFERENCES knowledge_bases(id) ON DELETE SET NULL,
                title VARCHAR(255) NOT NULL DEFAULT '新对话',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )""",
            """CREATE TABLE IF NOT EXISTS rag_messages (
                id SERIAL PRIMARY KEY,
                conversation_id INTEGER NOT NULL REFERENCES rag_conversations(id) ON DELETE CASCADE,
                role VARCHAR(20) NOT NULL,
                content TEXT NOT NULL,
                citations_json TEXT,
                memory_json TEXT,
                degraded BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )""",
            "CREATE INDEX IF NOT EXISTS ix_rag_conversations_user_id ON rag_conversations (user_id)",
            "CREATE INDEX IF NOT EXISTS ix_rag_conversations_kb_id ON rag_conversations (kb_id)",
            "CREATE INDEX IF NOT EXISTS ix_rag_messages_conversation_id ON rag_messages (conversation_id)",
        ),
    ),
    Migration(
        version="20260620_04",
        name="user_keyword_memory",
        statements=(
            """CREATE TABLE IF NOT EXISTS user_memories (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                keyword VARCHAR(128) NOT NULL,
                category VARCHAR(32) NOT NULL DEFAULT 'other',
                weight FLOAT DEFAULT 1.0,
                source_conversation_id INTEGER REFERENCES rag_conversations(id) ON DELETE SET NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_user_memory_keyword UNIQUE (user_id, keyword, category)
            )""",
            "ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS keyword VARCHAR(128)",
            "UPDATE user_memories SET keyword = COALESCE(keyword, '') WHERE keyword IS NULL",
            "ALTER TABLE user_memories ALTER COLUMN keyword SET NOT NULL",
            "ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS category VARCHAR(32) DEFAULT 'other'",
            "UPDATE user_memories SET category = 'other' WHERE category IS NULL",
            "ALTER TABLE user_memories ALTER COLUMN category SET NOT NULL",
            "ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS weight FLOAT DEFAULT 1.0",
            "ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS source_conversation_id INTEGER",
            "ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
            "CREATE INDEX IF NOT EXISTS ix_user_memories_user_id ON user_memories (user_id)",
            "CREATE INDEX IF NOT EXISTS ix_user_memories_keyword ON user_memories (keyword)",
        ),
    ),
    Migration(
        version="20260620_05",
        name="rag_message_memory_and_unique_user_memory",
        statements=(
            "ALTER TABLE rag_messages ADD COLUMN IF NOT EXISTS memory_json TEXT",
            "ALTER TABLE rag_messages ADD COLUMN IF NOT EXISTS degraded BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
            "UPDATE user_memories SET category = 'other' WHERE category IS NULL",
            "ALTER TABLE user_memories ALTER COLUMN category SET DEFAULT 'other'",
            "ALTER TABLE user_memories ALTER COLUMN category SET NOT NULL",
            """DELETE FROM user_memories older USING user_memories newer
               WHERE older.id < newer.id
                 AND older.user_id = newer.user_id
                 AND older.keyword = newer.keyword
                 AND older.category = newer.category""",
            """CREATE UNIQUE INDEX IF NOT EXISTS uq_user_memory_keyword
               ON user_memories (user_id, keyword, category)""",
        ),
    ),
    Migration(
        version="20260620_06",
        name="conversation_compaction_state",
        statements=(
            "ALTER TABLE rag_conversations ADD COLUMN IF NOT EXISTS summary TEXT",
            "ALTER TABLE rag_conversations ADD COLUMN IF NOT EXISTS summary_until_message_id INTEGER",
            "ALTER TABLE rag_conversations ADD COLUMN IF NOT EXISTS task_state_json TEXT",
        ),
    ),
    Migration(
        version="20260621_01",
        name="short_term_memory_extraction_checkpoint",
        statements=(
            "ALTER TABLE rag_messages ADD COLUMN IF NOT EXISTS memory_extracted BOOLEAN NOT NULL DEFAULT FALSE",
            "UPDATE rag_messages SET memory_extracted = TRUE WHERE role <> 'user'",
        ),
    ),
    Migration(
        version="20260621_02",
        name="user_password_column_compatibility",
        statements=(
            """DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'users'
                      AND column_name = 'password_hash'
                ) AND NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'users'
                      AND column_name = 'password'
                ) THEN
                    ALTER TABLE users RENAME COLUMN password_hash TO password;
                END IF;
            END $$""",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS password VARCHAR",
        ),
    ),
)


def _ensure_migration_table(connection) -> None:
    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS app_schema_migrations (
                version VARCHAR(100) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
    )


def _applied_versions(connection) -> set[str]:
    result = connection.execute(text("SELECT version FROM app_schema_migrations"))
    return set(result.scalars().all())


def run_migrations(engine: Engine, migrations: Iterable[Migration] = MIGRATIONS) -> None:
    """以单事务执行尚未应用的 PostgreSQL 迁移。

    非 PostgreSQL 测试数据库依赖 Base.metadata.create_all 创建最新结构，
    因此跳过 PostgreSQL 专用 advisory lock 和 DDL。
    """
    if engine.dialect.name != "postgresql":
        logger.info("skipping PostgreSQL migrations", extra={"dialect": engine.dialect.name})
        return
    # PostgreSQL 专用 advisory lock，防止其他事务同时执行迁移。
    with engine.begin() as connection:
        connection.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": MIGRATION_LOCK_ID})
        _ensure_migration_table(connection)
        applied = _applied_versions(connection)

        for migration in migrations:
            if migration.version in applied:
                continue
            logger.info("applying migration %s: %s", migration.version, migration.name)
            for statement in migration.statements:
                connection.execute(text(statement))
            connection.execute(
                text(
                    "INSERT INTO app_schema_migrations (version, name) "
                    "VALUES (:version, :name)"
                ),
                {"version": migration.version, "name": migration.name},
            )
            logger.info("applied migration %s", migration.version)


__all__ = ["MIGRATIONS", "Migration", "run_migrations"]
