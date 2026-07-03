"""长对话上下文压缩、结构化笔记与最近消息窗口"""
from __future__ import annotations

from dataclasses import dataclass
import json

from sqlalchemy.orm import Session

from app.core.config import (
    RAG_COMPACTION_THRESHOLD,
    RAG_HISTORY_MESSAGES,
    RAG_SUMMARY_MAX_CHARS,
)
from app.models import RagConversation, RagMessage
from app.services.short_term_memory import load_short_term_messages


@dataclass(frozen=True)
class ConversationContext:
    history: str
    task_state: str
    compacted: bool


def _value(message, name: str):
    return message.get(name) if isinstance(message, dict) else getattr(message, name)


def _role_line(message, max_chars: int = 1200) -> str:
    labels = {"user": "用户", "assistant": "助手", "system": "系统"}
    role = _value(message, "role")
    content = " ".join(_value(message, "content").split())[:max_chars]
    return f"- {labels.get(role, role)}：{content}"


def _task_state(messages: list[RagMessage]) -> dict:
    user_messages = [message for message in messages if message.role == "user"]
    if not user_messages:
        return {"goal": "", "recent_requests": []}
    return {
        "goal": " ".join(user_messages[0].content.split())[:500],
        "recent_requests": [
            " ".join(message.content.split())[:500]
            for message in user_messages[-3:]
        ],
    }


def _merge_summary(previous: str, messages: list[RagMessage]) -> str:
    sections = []
    if previous:
        sections.append(previous.strip())
    if messages:
        sections.append("阶段记录：\n" + "\n".join(_role_line(row) for row in messages))
    combined = "\n\n".join(sections)
    # Keep the most recent compacted notes; full messages remain in PostgreSQL.
    return combined[-RAG_SUMMARY_MAX_CHARS:]


def build_conversation_context(
    db: Session,
    conversation: RagConversation | None,
) -> ConversationContext:
    if conversation is None:
        return ConversationContext("（无历史对话", "（无任务状态）", False)

    uncompressed = (
        db.query(RagMessage)
        .filter(
            RagMessage.conversation_id == conversation.id,
            RagMessage.id > (conversation.summary_until_message_id or 0),
        )
        .order_by(RagMessage.id)
        .all()
    )
    state_messages = list(uncompressed)
    compacted = False
    if len(uncompressed) >= RAG_COMPACTION_THRESHOLD:
        compact_count = max(0, len(uncompressed) - RAG_HISTORY_MESSAGES)
        rows_to_compact = uncompressed[:compact_count]
        if rows_to_compact:
            conversation.summary = _merge_summary(conversation.summary or "", rows_to_compact)
            conversation.summary_until_message_id = rows_to_compact[-1].id
            uncompressed = uncompressed[compact_count:]
            compacted = True

    recent = []
    if RAG_HISTORY_MESSAGES:
        recent = load_short_term_messages(
            db,
            conversation.user_id,
            conversation.id,
            limit=RAG_HISTORY_MESSAGES,
        )
        checkpoint = conversation.summary_until_message_id or 0
        recent = [row for row in recent if row["message_id"] > checkpoint]
    state = _task_state(state_messages)
    try:
        previous_state = json.loads(conversation.task_state_json or "{}")
    except (TypeError, json.JSONDecodeError):
        previous_state = {}
    if previous_state.get("goal"):
        state["goal"] = previous_state["goal"]
    conversation.task_state_json = json.dumps(state, ensure_ascii=False)

    history_parts = []
    if conversation.summary:
        history_parts.append("【历史压缩摘要】\n" + conversation.summary)
    if recent:
        history_parts.append("【最近原始消息】\n" + "\n".join(_role_line(row) for row in recent))
    task_text = (
        f"目标：{state['goal'] or '未明确'}\n"
        + "最近请求：\n"
        + "\n".join(f"- {item}" for item in state["recent_requests"])
    )
    return ConversationContext("\n\n".join(history_parts) or "（无历史对话", task_text, compacted)
