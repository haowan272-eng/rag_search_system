"""用户长期记忆：只由 RAG 回答主链路产生和消费。"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Float, UniqueConstraint, func

from app.core.database import Base


class UserMemory(Base):
    __tablename__ = "user_memories"
    __table_args__ = (
        UniqueConstraint("user_id", "keyword", "category", name="uq_user_memory_keyword"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    keyword = Column(String(128), nullable=False, index=True)
    category = Column(String(32), nullable=False, default="other", comment="destination / preference / budget / constraint / other")
    weight = Column(Float, default=1.0, comment="重复提取时递增权重")
    source_conversation_id = Column(Integer, ForeignKey("rag_conversations.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
