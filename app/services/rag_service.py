"""RAG应用服务：编排唯一问答链路，不处理HTTP依赖注入"""
from __future__ import annotations

import json
import contextvars
import logging
import queue
import threading
from typing import Callable, Iterator, Optional

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Document, KnowledgeBaseMember, RagConversation, RagMessage, User
from app.rag.answering import (
    build_evidence,
    extractive_fallback,
    get_rag_answerer,
    validate_answer_citations,
)
from app.rag.chain import Retriever
from app.rag.embeddings import get_embedder
from app.schemas.rag import (
    AnswerRequest,
    AnswerResponse,
    CitationResult,
    MemoryResult,
)
from app.services.conversation_context import build_conversation_context
from app.services.memory_service import (
    load_memory,
    memory_context,
    remember_short_term_window,
    retrieval_query,
)
from app.services.short_term_memory import append_short_term_message
from app.core.database import SessionLocal

logger = logging.getLogger(__name__)


def _get_user(db: Session, username: str) -> User:
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=401, detail="用户不存")
    return user


def _private_conversation(
    db: Session,
    conversation_id: int,
    user_id: int,
) -> RagConversation:
    row = db.query(RagConversation).filter(
        RagConversation.id == conversation_id,
        RagConversation.user_id == user_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="对话不存")
    return row


def _effective_kb(
    body: AnswerRequest,
    conversation: Optional[RagConversation],
) -> Optional[int]:
    effective = body.kb_id
    if conversation and conversation.kb_id is not None:
        if effective is not None and effective != conversation.kb_id:
            raise HTTPException(status_code=400, detail="请求知识库与对话知识库不一")
        effective = conversation.kb_id
    return effective


def _ensure_kb_viewer(db: Session, user_id: int, kb_id: int) -> None:
    membership = db.query(KnowledgeBaseMember).filter(
        KnowledgeBaseMember.kb_id == kb_id,
        KnowledgeBaseMember.user_id == user_id,
    ).first()
    if not membership:
        raise HTTPException(status_code=403, detail="您不是该知识库的成员")


def _validate_document(
    db: Session,
    document_id: Optional[int],
    kb_id: Optional[int],
    user: User,
) -> None:
    if document_id is None:
        return
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="文档不存在")
    if document.kb_id is None:
        if kb_id is not None:
            raise HTTPException(status_code=400, detail="个人文档不属于指定知识库")
        if document.user_id != user.id:
            raise HTTPException(status_code=403, detail="无权访问该个人文档")
        return
    if kb_id is not None and document.kb_id != kb_id:
        raise HTTPException(status_code=400, detail="文档不属于指定知识库")
    _ensure_kb_viewer(db, user.id, document.kb_id)

def run_rag_answer(
    db: Session,
    username: str,
    body: AnswerRequest,
    on_token: Optional[Callable[[str], None]] = None,
) -> AnswerResponse:
    user = _get_user(db, username)
    conversation = (
        _private_conversation(db, body.conversation_id, user.id)
        if body.conversation_id is not None
        else None
    )
    effective_kb_id = _effective_kb(body, conversation)
    if effective_kb_id is not None:
        _ensure_kb_viewer(db, user.id, effective_kb_id)
    _validate_document(db, body.document_id, effective_kb_id, user)
    context_state = build_conversation_context(db, conversation)

    if conversation is None:
        conversation = RagConversation(
            user_id=user.id,
            kb_id=effective_kb_id,
            title=body.query[:80],
            task_state_json=json.dumps(
                {"goal": body.query[:500], "recent_requests": [body.query[:500]]},
                ensure_ascii=False,
            ),
        )
        db.add(conversation)
        db.flush()
    user_message = RagMessage(
        conversation_id=conversation.id,
        role="user",
        content=body.query,
        memory_extracted=not body.use_memory,
    )
    db.add(user_message)
    conversation.updated_at = func.now()
    db.commit()
    db.refresh(user_message)
    append_short_term_message(
        user.id,
        conversation.id,
        user_message.id,
        user_message.role,
        user_message.content,
        user_message.created_at,
    )
    if body.use_memory:
        remember_short_term_window(db, user.id, conversation.id)
        db.commit()

    memories = load_memory(db, user.id) if body.use_memory else []
    search_query = retrieval_query(body.query, memories)
    personal_space_only = effective_kb_id is None and body.document_id is None
    retrieval_user_id = user.id if personal_space_only else None
    try:
        embedder = get_embedder()
        bm25_weight = body.bm25_weight
        if bm25_weight > 0:
            try:
                embedder.ensure_bm25(
                    db,
                    user_id=retrieval_user_id,
                    document_id=body.document_id,
                    kb_id=effective_kb_id,
                    personal_space_only=personal_space_only,
                )
            except Exception:
                bm25_weight = 0.0
        results = Retriever(embedder).retrieve(
            query=search_query,
            top_k=body.top_k,
            document_id=body.document_id,
            user_id=retrieval_user_id,
            kb_id=effective_kb_id,
            personal_space_only=personal_space_only,
            bm25_weight=bm25_weight,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"知识检索暂时不可用: {exc}") from exc

    evidence, records = build_evidence(results)
    degraded = False
    if not records:
        answer = "知识库中未找到足够信息，暂时无法回答该问题。"
        response_records = []
    else:
        try:
            answerer = get_rag_answerer()
            generation_args = {
                "question": body.query,
                "context": evidence,
                "history": context_state.history,
                "memory": memory_context(memories),
                "task_state": context_state.task_state,
            }
            if on_token is None:
                answer = answerer.answer(**generation_args)
            else:
                chunks = []
                for token in answerer.stream(**generation_args):
                    chunks.append(token)
                    on_token(token)
                answer = "".join(chunks).strip()
            answer, response_records = validate_answer_citations(answer, records)
            if not response_records:
                raise ValueError("回答模型未返回有效引")
        except Exception:
            answer, response_records = extractive_fallback(records)
            degraded = True

    citations = [CitationResult(**record.as_dict()) for record in response_records]
    memory_payload = [item.as_dict() for item in memories]
    assistant_message = RagMessage(
        conversation_id=conversation.id,
        role="assistant",
        content=answer,
        citations_json=json.dumps(
            [citation.model_dump() for citation in citations],
            ensure_ascii=False,
        ),
        memory_json=json.dumps(memory_payload, ensure_ascii=False),
        memory_extracted=True,
        degraded=degraded,
    )
    db.add(assistant_message)
    conversation.updated_at = func.now()
    db.commit()
    db.refresh(assistant_message)
    append_short_term_message(
        user.id,
        conversation.id,
        assistant_message.id,
        assistant_message.role,
        assistant_message.content,
        assistant_message.created_at,
    )

    return AnswerResponse(
        query=body.query,
        answer=answer,
        conversation_id=conversation.id,
        citations=citations,
        retrieved_count=len(results),
        memory_used=[MemoryResult(**item) for item in memory_payload],
        degraded=degraded,
        context_compacted=context_state.compacted,
    )


class _ClientDisconnected(RuntimeError):
    pass


def stream_rag_answer(username: str, body: AnswerRequest) -> Iterator[dict]:
    """Run the existing RAG transaction in a worker thread and emit bounded SSE events."""
    events: queue.Queue[dict] = queue.Queue(maxsize=100)
    stopped = threading.Event()
    request_context = contextvars.copy_context()

    def emit(event: str, data: dict) -> None:
        while not stopped.is_set():
            try:
                events.put({"event": event, "data": data}, timeout=0.5)
                return
            except queue.Full:
                continue
        raise _ClientDisconnected()

    def execute() -> None:
        db = SessionLocal()
        try:
            result = run_rag_answer(
                db,
                username,
                body,
                on_token=lambda token: emit("token", {"delta": token}),
            )
            emit("final", result.model_dump(mode="json"))
        except _ClientDisconnected:
            logger.info("SSE client disconnected before completion")
        except HTTPException as exc:
            try:
                emit("error", {"status_code": exc.status_code, "detail": exc.detail})
            except _ClientDisconnected:
                pass
        except Exception:
            logger.exception("streaming RAG answer failed")
            try:
                emit("error", {"status_code": 500, "detail": "回答生成失败，请稍后重试"})
            except _ClientDisconnected:
                pass
        finally:
            db.close()
            try:
                emit("done", {})
            except _ClientDisconnected:
                pass

    thread = threading.Thread(
        target=lambda: request_context.run(execute),
        name="rag-sse-answer",
        daemon=True,
    )
    thread.start()
    try:
        while True:
            item = events.get()
            yield item
            if item["event"] == "done":
                return
    finally:
        stopped.set()

