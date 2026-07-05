"""Query rewriting for rewrite-retrieve-read RAG."""
from __future__ import annotations

from typing import Optional

from app.core.config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    RAG_ANSWER_MAX_RETRIES,
    RAG_ANSWER_TIMEOUT_SECONDS,
    RAG_QUERY_REWRITE_MAX_CHARS,
    RAG_QUERY_REWRITE_TEMPERATURE,
)


class LangChainQueryRewriter:
    """Rewrite a contextual user question into a standalone retrieval query."""

    def __init__(self):
        self._chain = None

    def _build_chain(self):
        if not DEEPSEEK_API_KEY:
            raise RuntimeError("未配置 DEEPSEEK_API_KEY，无法改写检索问题")
        from langchain_core.output_parsers import StrOutputParser
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_openai import ChatOpenAI

        prompt = ChatPromptTemplate.from_messages([
            (
                "system",
                """你是 RAG 检索 Query 改写器，负责执行 rewrite-retrieve-read 中的 rewrite 步骤。
目标：把用户当前问题改写为适合知识库检索的独立中文检索问题。
规则：
1. 只输出改写后的检索问题，不要回答问题，不要解释。
2. 保留用户原始意图、限定条件、实体名、时间、数量、格式要求和关键术语。
3. 根据最近对话补全省略、指代和上下文依赖，例如“它”“这个方案”“上面那个”。
4. 私人长期记忆只能用于补全偏好、约束或检索范围，不能编造事实。
5. 不要加入对话和记忆中没有依据的新实体、新数字、新结论。
6. 如果当前问题已经独立清晰，尽量保持原样，只做必要的关键词增强。
7. 输出应适合 BM25 + 向量检索，优先使用自然语言短问题，可附带关键同义词。""",
            ),
            (
                "human",
                """【私人长期记忆】
{memory}

【最近对话】
{history}

【当前任务状态】
{task_state}

【用户当前问题】
{question}

请输出一个独立、清晰、适合知识库检索的 Query。""",
            ),
        ])
        model = ChatOpenAI(
            model=DEEPSEEK_MODEL,
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
            temperature=RAG_QUERY_REWRITE_TEMPERATURE,
            max_tokens=256,
            timeout=RAG_ANSWER_TIMEOUT_SECONDS,
            max_retries=RAG_ANSWER_MAX_RETRIES,
            streaming=False,
        )
        self._chain = prompt | model | StrOutputParser()
        return self._chain

    @property
    def chain(self):
        return self._chain or self._build_chain()

    def rewrite(
        self,
        question: str,
        history: str,
        memory: str,
        task_state: str,
    ) -> str:
        rewritten = self.chain.invoke({
            "question": question,
            "history": history or "（无历史对话）",
            "memory": memory or "（无长期记忆）",
            "task_state": task_state or "（无任务状态）",
        }).strip()
        rewritten = _clean_rewritten_query(rewritten)
        return rewritten or question


def _clean_rewritten_query(value: str) -> str:
    text = " ".join((value or "").strip().split())
    if len(text) > RAG_QUERY_REWRITE_MAX_CHARS:
        return text[:RAG_QUERY_REWRITE_MAX_CHARS].strip()
    return text


_query_rewriter: Optional[LangChainQueryRewriter] = None


def get_query_rewriter() -> LangChainQueryRewriter:
    global _query_rewriter
    if _query_rewriter is None:
        _query_rewriter = LangChainQueryRewriter()
    return _query_rewriter