"""RAG Agent 服务 - 基于 LangGraph 的智能代理

使用 langchain_qwq 的 ChatQwen 原生集成，
支持真正的流式输出和更好的模型适配。
"""

import asyncio
from collections import OrderedDict
import re
from time import perf_counter
from typing import Annotated, Any, AsyncGenerator, Dict, Sequence

from langchain.agents import create_agent
from langchain.agents.middleware import before_model
from langchain_core.documents import Document
from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
)
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.message import REMOVE_ALL_MESSAGES, add_messages
from loguru import logger
from typing_extensions import TypedDict
from langchain_qwq import ChatQwen

from app.config import config
from app.tools import get_current_time, retrieve_knowledge
from app.services.local_knowledge_search_service import local_knowledge_search_service
from app.services.vector_store_manager import vector_store_manager

CATALOG_FILE_NAME = "ai_video_prompt_kb_catalog.md"

# 阿里千问大模型和langchain集成参考： https://docs.langchain.com/oss/python/integrations/chat/qwen
# 注意：需要配置环境变量 DASHSCOPE_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1 否则默认访问的是新加坡站点
# 同时也需要配置环境变量 DASHSCOPE_API_KEY=your_api_key


class AgentState(TypedDict):
    """Agent 状态"""
    messages: Annotated[Sequence[BaseMessage], add_messages]


@before_model(state_schema=AgentState)
def trim_messages_middleware(state: AgentState, _runtime: Any) -> dict[str, Any] | None:
    """
    修剪消息历史，只保留最近的几条消息以适应上下文窗口

    策略：
    - 保留最新系统消息（System Message）
    - 保留最近的 6 条消息（3 轮对话）
    - 当消息少于等于 7 条时，不做修剪

    Args:
        state: Agent 状态

    Returns:
        包含修剪后消息的字典，如果无需修剪则返回 None
    """
    messages = list(state["messages"])

    # 如果消息数量较少，无需修剪
    if len(messages) <= 7:
        return None

    # 保留最新系统提示词，避免历史中的旧系统提示词继续膨胀上下文。
    system_messages = [message for message in messages if isinstance(message, SystemMessage)]
    latest_system_message = system_messages[-1] if system_messages else None
    conversation_messages = [
        message for message in messages if not isinstance(message, SystemMessage)
    ]

    # 保留最近的 6 条消息（确保包含完整的对话轮次）
    recent_messages = conversation_messages[-6:]

    # 构建新的消息列表
    new_messages = (
        [latest_system_message, *recent_messages]
        if latest_system_message is not None
        else list(recent_messages)
    )

    logger.debug(f"修剪消息历史: {len(messages)} -> {len(new_messages)} 条")

    return {
        "messages": [
            RemoveMessage(id=REMOVE_ALL_MESSAGES),
            *new_messages
        ]
    }


class RagAgentService:
    """RAG Agent 服务 - 使用 LangGraph + ChatQwen 原生集成"""

    def __init__(self, streaming: bool = True):
        """初始化 RAG Agent 服务

        Args:
            streaming: 是否启用流式输出，默认为 True
        """
        self.model_name = config.rag_model
        self.streaming = streaming
        self.system_prompt = self._build_system_prompt()

        # 定义基础工具
        self.tools = [retrieve_knowledge, get_current_time]

        # 创建内存检查点（用于会话管理）
        self.checkpointer = MemorySaver()

        # Agent 按模型缓存，避免切换模型时每次请求都重建。
        self.agent = None
        self._agents: dict[str, Any] = {}
        self._models: dict[str, ChatQwen] = {}
        self._agent_init_locks: dict[str, asyncio.Lock] = {}
        self._grounding_cache: OrderedDict[str, tuple[float, list[Document]]] = OrderedDict()
        self._grounded_prompt_cache: OrderedDict[str, tuple[float, str, str]] = OrderedDict()

        logger.info(f"RAG Agent 服务初始化完成 (ChatQwen), model={self.model_name}, streaming={streaming}")

    def _normalize_model_name(self, model_name: str | None = None) -> str:
        return (model_name or self.model_name or config.rag_model or "qwen3.7-plus").strip()

    def _create_chat_model(self, model_name: str) -> ChatQwen:
        return ChatQwen(
            model=model_name,
            api_key=config.dashscope_api_key,
            base_url=config.dashscope_base_url,
            timeout=config.dashscope_request_timeout_seconds,
            max_retries=config.dashscope_max_retries,
            temperature=0.2,
            streaming=self.streaming,
            enable_thinking=False,
        )

    async def _initialize_agent(self, model_name: str | None = None) -> str:
        """异步初始化 Agent。"""
        selected_model = self._normalize_model_name(model_name)
        if selected_model in self._agents:
            return selected_model

        if selected_model not in self._agent_init_locks:
            self._agent_init_locks[selected_model] = asyncio.Lock()

        async with self._agent_init_locks[selected_model]:
            if selected_model in self._agents:
                return selected_model

            init_started_at = perf_counter()

            all_tools = self.tools

            agent_build_started_at = perf_counter()
            model = self._create_chat_model(selected_model)
            agent = create_agent(
                model,
                tools=all_tools,
                middleware=[trim_messages_middleware],
                checkpointer=self.checkpointer,
            )
            agent_build_elapsed_ms = (perf_counter() - agent_build_started_at) * 1000

            self._models[selected_model] = model
            self._agents[selected_model] = agent
            if selected_model == self.model_name:
                self.agent = agent

            if all_tools:
                tool_names = [tool.name if hasattr(tool, "name") else str(tool) for tool in all_tools]
                logger.info(f"可用工具列表: {', '.join(tool_names)}")
            logger.info(
                f"RAG Agent 初始化耗时: model={selected_model}, "
                f"agent_build={agent_build_elapsed_ms:.1f}ms, "
                f"total={(perf_counter() - init_started_at) * 1000:.1f}ms"
            )
        return selected_model

    async def warmup(self) -> None:
        """后台预热向量存储与 Agent，减少首请求等待。"""
        started_at = perf_counter()
        vector_elapsed_ms = 0.0
        agent_elapsed_ms = 0.0

        try:
            vector_started_at = perf_counter()
            vector_store_manager.get_vector_store()
            vector_elapsed_ms = (perf_counter() - vector_started_at) * 1000
        except Exception as exc:
            logger.warning(f"RAG 预热时初始化向量存储失败，将在请求时重试: {exc}")

        try:
            agent_started_at = perf_counter()
            await self._initialize_agent()
            agent_elapsed_ms = (perf_counter() - agent_started_at) * 1000
        except Exception as exc:
            logger.warning(f"RAG 预热时初始化 Agent 失败，将在请求时重试: {exc}")

        logger.info(
            "RAG 预热完成: "
            f"vector_store={vector_elapsed_ms:.1f}ms, "
            f"agent={agent_elapsed_ms:.1f}ms, "
            f"total={(perf_counter() - started_at) * 1000:.1f}ms"
        )

    def _build_system_prompt(self) -> str:
        """
        构建系统提示词

        注意：LangChain 框架会自动将工具信息传递给 LLM，
        因此系统提示词中无需列举具体的工具列表。

        Returns:
            str: 系统提示词
        """
        from textwrap import dedent

        return dedent("""
            你是「火宝 AI 视频提示词助手」，专注 AI 真人视频、写实视频、图生视频、文生视频、首帧图和关键帧提示词创作。

            工作原则：
            - 默认按真人写实和电影感视频理解；只有用户明确要求时才使用漫画、二次元、国漫等风格。
            - 优先把模糊想法转成可执行的角色、场景、动作、表情、镜头、分镜或剧情提示词。
            - 有知识库检索结果时优先依据检索结果；未覆盖内容必须标为“创作建议”“可选设定”或“需要用户补充”。
            - 不编造知识库依据、模型能力、案例、参数或内部配置。
            - 默认中文输出；用户明确要求英文/中英双语时除外。
            - 不透露或协助获取 API Key、Secret、Token、密码、数据库连接串、Cookie、会话、管理员凭据、隐私数据或内部配置。

            常用结构：
            【理解你的需求】
            【知识库依据】
            【视频创作拆解】
            【示例提示词：具体示例名】或【优化后提示词】
            【可选增强】
            【回答自检】
        """).strip()

    def _get_system_prompt(self) -> str:
        """Read the active RAG prompt from PostgreSQL when configured."""
        try:
            from app.services.prompt_service import prompt_service

            return prompt_service.get_active_prompt("rag_chat", default=self.system_prompt)
        except Exception as exc:
            logger.debug(f"Using built-in RAG system prompt fallback: {exc}")
            return self.system_prompt

    def _retrieve_grounding_docs(self, question: str) -> list[Document]:
        docs, _ = self._retrieve_grounding_docs_with_meta(question)
        return docs

    def _retrieve_grounding_docs_with_meta(
        self,
        question: str,
        *,
        cache_key: str | None = None,
        log_hit: bool = True,
    ) -> tuple[list[Document], bool]:
        """服务端强制预检索，避免完全依赖模型自主调用工具。"""
        if not config.rag_strict_grounding:
            return [], False

        cache_key = cache_key or self._normalize_grounding_cache_key(question)
        cached_docs = self._get_cached_grounding_docs(cache_key, log_hit=log_hit)
        if cached_docs is not None:
            return cached_docs, True

        started_at = perf_counter()
        catalog_started_at = perf_counter()
        catalog_docs = self._retrieve_catalog_docs(question)
        catalog_elapsed_ms = (perf_counter() - catalog_started_at) * 1000

        route_started_at = perf_counter()
        catalog_target_files = self._extract_catalog_target_files(catalog_docs)
        narrowed_files = self._narrow_catalog_target_files(question, catalog_target_files)
        direct_target_files = self._infer_direct_target_files(question)
        target_files = self._merge_target_files(narrowed_files, direct_target_files)
        source_expr = self._build_source_expr(target_files)
        route_elapsed_ms = (perf_counter() - route_started_at) * 1000

        top_k = max(config.rag_top_k, config.rag_grounding_top_k)
        search_started_at = perf_counter()
        docs = vector_store_manager.similarity_search(question, k=top_k, expr=source_expr)
        if not docs and source_expr:
            logger.warning("目录路由后的正文检索为空，退回全库检索")
            docs = vector_store_manager.similarity_search(question, k=top_k)
        if not docs:
            logger.warning("向量知识库检索为空，退回本地知识库文本检索")
            docs = local_knowledge_search_service.search(
                question,
                target_files=target_files,
                k=top_k,
            )
        docs = self._filter_enabled_admin_docs(docs)
        search_elapsed_ms = (perf_counter() - search_started_at) * 1000

        filter_started_at = perf_counter()
        filtered_docs = self._filter_grounding_docs(question, docs)
        filter_elapsed_ms = (perf_counter() - filter_started_at) * 1000
        logger.info(
            f"强制知识库预检索完成: catalog={len(catalog_docs)}, "
            f"catalog_target_files={catalog_target_files}, direct_target_files={direct_target_files}, "
            f"target_files={target_files}, top_k={top_k}, 命中={len(docs)}, 使用={len(filtered_docs)}, "
            f"catalog={catalog_elapsed_ms:.1f}ms, route={route_elapsed_ms:.1f}ms, "
            f"search={search_elapsed_ms:.1f}ms, filter={filter_elapsed_ms:.1f}ms, "
            f"total={(perf_counter() - started_at) * 1000:.1f}ms"
        )
        self._store_grounding_docs_cache(cache_key, filtered_docs)
        return filtered_docs, False

    def _filter_enabled_admin_docs(self, docs: list[Document]) -> list[Document]:
        """For admin-managed chunks, verify enabled/deleted/status in PostgreSQL."""
        admin_chunk_ids: list[int] = []
        for doc in docs:
            metadata = doc.metadata or {}
            chunk_id = metadata.get("chunk_id")
            document_id = metadata.get("document_id")
            if chunk_id is None or document_id is None:
                continue
            try:
                admin_chunk_ids.append(int(chunk_id))
            except (TypeError, ValueError):
                continue

        if not admin_chunk_ids:
            return docs

        try:
            from app.core.database import get_connection

            with get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT c.id
                        FROM kb_document_chunks c
                        JOIN kb_documents d ON d.id = c.document_id
                        WHERE c.id = ANY(%s)
                          AND c.enabled = TRUE
                          AND d.enabled = TRUE
                          AND d.is_deleted = FALSE
                          AND d.vector_status = 'success'
                        """,
                        (admin_chunk_ids,),
                    )
                    allowed = {int(row["id"]) for row in cursor.fetchall()}
        except Exception as exc:
            logger.warning(f"Failed to verify admin KB chunk status, keeping vector hits: {exc}")
            return docs

        filtered: list[Document] = []
        for doc in docs:
            metadata = doc.metadata or {}
            chunk_id = metadata.get("chunk_id")
            document_id = metadata.get("document_id")
            if chunk_id is None or document_id is None:
                filtered.append(doc)
                continue
            try:
                if int(chunk_id) in allowed:
                    filtered.append(doc)
            except (TypeError, ValueError):
                filtered.append(doc)
        return filtered

    def _normalize_grounding_cache_key(self, question: str) -> str:
        return question.strip()

    def _get_cached_grounding_docs(
        self,
        cache_key: str,
        *,
        log_hit: bool = True,
    ) -> list[Document] | None:
        ttl_seconds = config.rag_grounding_cache_ttl_seconds
        if ttl_seconds <= 0 or not cache_key:
            return None

        self._prune_grounding_cache()
        cached = self._grounding_cache.get(cache_key)
        if not cached:
            return None

        cached_at, docs = cached
        if perf_counter() - cached_at > ttl_seconds:
            self._grounding_cache.pop(cache_key, None)
            return None

        self._grounding_cache.move_to_end(cache_key)
        if log_hit:
            logger.info(f"命中知识库预检索缓存: key_length={len(cache_key)}, docs={len(docs)}")
        return list(docs)

    def _store_grounding_docs_cache(self, cache_key: str, docs: list[Document]) -> None:
        ttl_seconds = config.rag_grounding_cache_ttl_seconds
        if ttl_seconds <= 0 or not cache_key:
            return
        if not docs:
            self._grounding_cache.pop(cache_key, None)
            self._grounded_prompt_cache.pop(cache_key, None)
            return

        self._grounding_cache[cache_key] = (perf_counter(), list(docs))
        self._grounding_cache.move_to_end(cache_key)
        self._prune_grounding_cache()

    def _get_cached_grounded_prompt(
        self,
        cache_key: str,
        *,
        docs_signature: str,
        log_hit: bool = True,
    ) -> str | None:
        ttl_seconds = config.rag_grounding_cache_ttl_seconds
        if ttl_seconds <= 0 or not cache_key or not docs_signature:
            return None

        self._prune_grounded_prompt_cache()
        cached = self._grounded_prompt_cache.get(cache_key)
        if not cached:
            return None

        cached_at, prompt, cached_signature = cached
        if perf_counter() - cached_at > ttl_seconds:
            self._grounded_prompt_cache.pop(cache_key, None)
            return None
        if cached_signature != docs_signature:
            self._grounded_prompt_cache.pop(cache_key, None)
            return None

        self._grounded_prompt_cache.move_to_end(cache_key)
        if log_hit:
            logger.info(f"Hit grounded prompt cache: key_length={len(cache_key)}")
        return prompt

    def _store_grounded_prompt_cache(self, cache_key: str, prompt: str, docs_signature: str) -> None:
        ttl_seconds = config.rag_grounding_cache_ttl_seconds
        if ttl_seconds <= 0 or not cache_key or not prompt or not docs_signature:
            return
        if docs_signature == "empty":
            self._grounded_prompt_cache.pop(cache_key, None)
            return

        self._grounded_prompt_cache[cache_key] = (perf_counter(), prompt, docs_signature)
        self._grounded_prompt_cache.move_to_end(cache_key)
        self._prune_grounded_prompt_cache()

    def _prune_grounding_cache(self) -> None:
        ttl_seconds = config.rag_grounding_cache_ttl_seconds
        max_entries = max(1, config.rag_grounding_cache_max_entries)
        now = perf_counter()

        expired_keys = [
            cache_key
            for cache_key, (cached_at, _) in self._grounding_cache.items()
            if now - cached_at > ttl_seconds
        ]
        for cache_key in expired_keys:
            self._grounding_cache.pop(cache_key, None)

        while len(self._grounding_cache) > max_entries:
            self._grounding_cache.popitem(last=False)

    def _prune_grounded_prompt_cache(self) -> None:
        ttl_seconds = config.rag_grounding_cache_ttl_seconds
        max_entries = max(1, config.rag_grounding_cache_max_entries)
        now = perf_counter()

        expired_keys = [
            cache_key
            for cache_key, (cached_at, _, _) in self._grounded_prompt_cache.items()
            if now - cached_at > ttl_seconds
        ]
        for cache_key in expired_keys:
            self._grounded_prompt_cache.pop(cache_key, None)

        while len(self._grounded_prompt_cache) > max_entries:
            self._grounded_prompt_cache.popitem(last=False)

    def clear_grounding_cache(self, reason: str = "manual") -> None:
        cleared = len(self._grounding_cache)
        cleared_prompts = len(self._grounded_prompt_cache)
        self._grounding_cache.clear()
        self._grounded_prompt_cache.clear()
        logger.info(
            f"已清空知识库预检索缓存: reason={reason}, doc_entries={cleared}, prompt_entries={cleared_prompts}"
        )

    def _collect_grounding_metrics(self, question: str) -> dict[str, Any]:
        cache_key = self._normalize_grounding_cache_key(question)
        grounding_docs, doc_cache_hit = self._retrieve_grounding_docs_with_meta(
            question,
            cache_key=cache_key,
            log_hit=False,
        )
        grounded_question, prompt_cache_hit = self._build_grounded_user_prompt_with_meta(
            question,
            grounding_docs,
            cache_key=cache_key,
            log_hit=False,
        )
        return {
            "doc_cache_hit": doc_cache_hit,
            "prompt_cache_hit": prompt_cache_hit,
            "docs": grounding_docs,
            "grounded_question": grounded_question,
        }

    def _format_grounding_metrics_summary(
        self,
        *,
        doc_cache_hit: bool,
        prompt_cache_hit: bool,
        docs_count: int,
    ) -> str:
        return (
            f"grounding_cache={'hit' if doc_cache_hit else 'miss'}, "
            f"prompt_cache={'hit' if prompt_cache_hit else 'miss'}, "
            f"grounding_docs={docs_count}"
        )

    def _retrieve_catalog_docs(self, question: str) -> list[Document]:
        """先检索轻量目录，确定应该查哪个正文知识域。"""
        catalog_expr = f'metadata["_file_name"] == "{CATALOG_FILE_NAME}"'
        docs = vector_store_manager.similarity_search(
            question,
            k=config.rag_catalog_top_k,
            expr=catalog_expr,
        )
        if docs:
            return docs

        # 目录还没入库或 Milvus 表达式不可用时，退回一次无过滤检索，并只保留目录文档。
        fallback_docs = vector_store_manager.similarity_search(
            f"知识库目录 路由 {question}",
            k=config.rag_catalog_top_k,
        )
        return [
            doc
            for doc in fallback_docs
            if (doc.metadata or {}).get("_file_name") == CATALOG_FILE_NAME
        ]

    def _extract_catalog_target_files(self, catalog_docs: list[Document]) -> list[str]:
        """从目录文档中提取对应正文文件名。"""
        target_files: list[str] = []
        for doc in catalog_docs:
            content = doc.page_content or ""
            for file_name in re.findall(r"`([^`]+\.md)`", content):
                if file_name == CATALOG_FILE_NAME:
                    continue
                if file_name not in target_files:
                    target_files.append(file_name)
        return target_files

    def _merge_target_files(self, *file_groups: list[str]) -> list[str]:
        merged: list[str] = []
        for files in file_groups:
            for file_name in files:
                if file_name and file_name not in merged:
                    merged.append(file_name)
        return merged

    def _infer_direct_target_files(self, question: str) -> list[str]:
        """根据用户明示关键词补充直达知识文件，避免目录召回偏航。"""
        explicit_template = self._explicit_prompt_template(question)
        if explicit_template == "character":
            return [
                "ai_video_character_design_chunks.md",
                "ai_manga_character_three_view_prompt_chunks.md",
            ]
        if explicit_template == "scene":
            return ["ai_manga_image_scene_prompt_chunks.md"]
        if explicit_template == "expression":
            return ["ai_manga_expression_voice_prompt_chunks.md"]
        if explicit_template == "storyboard":
            return ["ai_video_script_structure_chunks.md"]
        if explicit_template == "plot":
            return ["ai_video_script_structure_chunks.md"]

        rules = [
            (
                "ai_video_action_naturalization_chunks.md",
                (
                    "动作",
                    "人物运动",
                    "角色动作",
                    "动作自然",
                    "动作不自然",
                    "动作僵硬",
                    "动作链",
                    "身体联动",
                    "走路",
                    "行走",
                    "步态",
                    "转身",
                    "回头",
                    "抬头",
                    "低头",
                    "伸手",
                    "触碰",
                    "机器人",
                    "互动",
                    "对视",
                    "镜头跟随",
                ),
            ),
            (
                "ai_video_style_aesthetics_chunks.md",
                (
                    "风格",
                    "美学",
                    "画风",
                    "视觉风格",
                    "风格关键词",
                    "AI 视频风格",
                    "二次元",
                    "动漫",
                    "动画",
                    "漫剧",
                    "吉卜力",
                    "新海诚",
                    "赛博朋克",
                    "水墨",
                    "Webtoon",
                    "皮克斯",
                    "迪士尼",
                ),
            ),
            (
                "ai_video_character_design_chunks.md",
                (
                    "角色",
                    "人物设定",
                    "角色设定",
                    "设定卡",
                    "一致性",
                    "像换人",
                    "换场景",
                    "脸型",
                    "发型",
                    "服装",
                    "参考图",
                    "多角度",
                    "图生图",
                ),
            ),
            (
                "ai_video_script_structure_chunks.md",
                (
                    "剧本",
                    "脚本",
                    "分镜",
                    "分场景",
                    "故事大纲",
                    "剧情",
                    "episode",
                    "scene",
                    "duration",
                    "JSON",
                    "json",
                ),
            ),
            (
                "ai_manga_image_scene_prompt_chunks.md",
                (
                    "图片生成",
                    "图片分析",
                    "场景提示词",
                    "场景生成",
                    "场景画面",
                    "视觉色卡",
                    "色卡",
                    "色调",
                    "光影",
                    "构图",
                ),
            ),
            (
                "ai_manga_expression_voice_prompt_chunks.md",
                (
                    "表情",
                    "语气",
                    "台词",
                    "眼神",
                    "眉毛",
                    "嘴角",
                    "面部细节",
                    "微表情",
                    "声音",
                ),
            ),
            (
                "ai_manga_character_three_view_prompt_chunks.md",
                (
                    "三视图",
                    "正视图",
                    "侧视图",
                    "后视图",
                    "人物三视图",
                    "角色三视图",
                    "角色模板",
                    "角色参考图",
                    "面部特写",
                    "character sheet",
                    "character reference",
                ),
            ),
        ]

        target_files: list[str] = []
        for file_name, keywords in rules:
            if any(keyword in question for keyword in keywords):
                target_files.append(file_name)
        return target_files

    def _build_source_expr(self, target_files: list[str]) -> str | None:
        if not target_files:
            return None
        escaped_files = [file_name.replace("\\", "\\\\").replace('"', '\\"') for file_name in target_files]
        values = ", ".join(f'"{file_name}"' for file_name in escaped_files)
        return f'metadata["_file_name"] in [{values}]'

    def _explicit_prompt_template(self, question: str) -> str | None:
        """Detect a template explicitly selected by the UI before heuristic routing."""
        q = question or ""
        markers = (
            ("character", ("任务类型：角色生成", "「角色生成」创作模板")),
            ("scene", ("任务类型：场景提示词", "「场景提示词」创作模板")),
            ("expression", ("任务类型：表情语气模板", "「表情语气」创作模板")),
            ("storyboard", ("任务类型：分镜脚本", "「分镜脚本」创作模板")),
            ("plot", ("任务类型：剧情策划", "「剧情提示词」创作模板")),
        )
        for template, template_markers in markers:
            if any(marker in q for marker in template_markers):
                return template
        return None

    def _is_expression_voice_request(self, question: str) -> bool:
        explicit_template = self._explicit_prompt_template(question)
        if explicit_template:
            return explicit_template == "expression"
        keywords = (
            "表情提示词",
            "表情语气",
            "台词语气",
            "表情模板",
            "语气模板",
            "面部细节",
            "微表情",
            "声音/台词",
            "声音台词",
            "情绪拆解",
            "眼神",
            "眉毛",
            "眼睑",
            "嘴角",
            "唇部",
            "说话语气",
        )
        return any(keyword in question for keyword in keywords)

    def _is_character_three_view_request(self, question: str, docs: list[Document] | None = None) -> bool:
        explicit_template = self._explicit_prompt_template(question)
        if explicit_template:
            return explicit_template == "character"
        keywords = (
            "三视图",
            "正视图",
            "侧视图",
            "后视图",
            "人物三视图",
            "角色三视图",
            "角色模板",
            "人物角色模板",
            "人物提示词",
            "角色提示词",
            "人物设定提示词",
            "角色设定提示词",
            "人物设定图",
            "角色设定图",
            "角色参考图",
            "完整人物设定",
            "角色卡",
            "人物卡",
            "人物定妆",
            "角色定妆",
            "角色一句话",
            "身份背景",
            "外貌识别",
            "服装道具",
            "性格与内在",
            "角色视频使用建议",
            "生成一个角色",
            "生成一位角色",
            "生成一名角色",
            "创建一个角色",
            "创建一位角色",
            "创建一名角色",
            "设计一个角色",
            "设计一位角色",
            "设计一名角色",
            "生成人物卡",
            "生成角色卡",
            "面部特写",
            "人设记忆点",
            "character sheet",
            "character reference",
        )
        legacy_character_template_markers = (
            "角色一句话",
            "身份背景",
            "外貌识别",
            "服装道具",
            "性格与内在",
            "角色视频使用建议",
            "江湖游侠",
            "阵营/关系",
            "过往经历",
            "当前处境",
        )
        character_detail_markers = (
            "角色设定",
            "人物设定",
            "角色卡",
            "人物卡",
            "三视图",
            "外貌",
            "服装",
            "身份",
            "性格",
            "人设记忆点",
            "视觉锚点",
        )
        file_names = {
            str((doc.metadata or {}).get("_file_name") or "")
            for doc in (docs or [])
        }
        if any(keyword in question for keyword in keywords):
            return True
        if any(marker in question for marker in legacy_character_template_markers):
            return True
        if "ai_manga_character_three_view_prompt_chunks.md" in file_names:
            return True

        creation_verbs = ("生成", "创建", "设计", "构建", "塑造", "补充", "写一个", "写一位", "做一个")
        role_nouns = ("角色", "人物", "侠客", "人设")
        looks_like_role_creation = any(verb in question for verb in creation_verbs) and any(
            noun in question for noun in role_nouns
        )
        if not looks_like_role_creation:
            return False

        # “生成人物表情语气模板”属于表情语气，不应被“人物/模板”误判为三视图角色卡。
        if self._is_expression_voice_request(question) and not any(
            marker in question for marker in character_detail_markers
        ):
            return False
        return True

    def _is_scene_or_image_prompt_request(self, question: str, docs: list[Document] | None = None) -> bool:
        explicit_template = self._explicit_prompt_template(question)
        if explicit_template:
            return explicit_template == "scene"
        keywords = (
            "图片分析",
            "分析图片",
            "图片生成提示词",
            "场景提示词",
            "场景生成",
            "场景画面",
            "视觉色卡",
            "色卡",
            "色调",
            "主色",
            "辅助色",
            "强调色",
            "阴影色",
            "光影",
            "构图",
            "世界观色调",
        )
        file_names = {
            str((doc.metadata or {}).get("_file_name") or "")
            for doc in (docs or [])
        }
        return (
            any(keyword in question for keyword in keywords)
            or "ai_manga_image_scene_prompt_chunks.md" in file_names
        )

    def _mentions_real_skin_request(self, question: str) -> bool:
        keywords = (
            "禁塑料感",
            "活人感",
            "真人感",
            "写实皮肤",
            "真实皮肤",
            "皮肤真实",
            "皮肤纹理",
            "毛孔",
            "皮肤微纹理",
        )
        return any(keyword in question for keyword in keywords)

    def _explicit_real_skin_request_for_character(self, question: str) -> bool:
        """旧角色模板里的“活人感细节”不等于用户要在人物卡里输出皮肤细节板块。"""
        keywords = (
            "禁塑料感",
            "真人感",
            "写实皮肤",
            "真实皮肤",
            "皮肤真实",
            "电影级剧照",
            "不要磨皮",
            "皮肤纹理",
            "毛孔",
            "皮肤微纹理",
        )
        return any(keyword in question for keyword in keywords)

    def _narrow_catalog_target_files(self, question: str, target_files: list[str]) -> list[str]:
        """用轻量关键词再收窄一次目录命中的正文文件，减少无关正文检索。"""
        if not target_files:
            return []

        explicit_template = self._explicit_prompt_template(question)
        explicit_files = {
            "character": [
                "ai_video_character_design_chunks.md",
                "ai_manga_character_three_view_prompt_chunks.md",
            ],
            "scene": ["ai_manga_image_scene_prompt_chunks.md"],
            "expression": ["ai_manga_expression_voice_prompt_chunks.md"],
            "storyboard": ["ai_video_script_structure_chunks.md"],
            "plot": ["ai_video_script_structure_chunks.md"],
        }.get(explicit_template)
        if explicit_files:
            narrowed = [file_name for file_name in explicit_files if file_name in target_files]
            if narrowed:
                return narrowed

        three_view_keywords = (
            "三视图",
            "正视图",
            "侧视图",
            "后视图",
            "角色模板",
            "人物设定图",
            "角色设定图",
            "角色参考图",
            "面部特写",
            "禁塑料感",
            "塑料皮肤",
            "毛孔",
            "皮肤微纹理",
            "活人感",
            "多人差异化",
            "人设记忆点",
            "怂帅",
            "恐女武僧",
            "月光娘炮",
            "character sheet",
            "character reference",
        )
        three_view_file = "ai_manga_character_three_view_prompt_chunks.md"
        expression_file = "ai_manga_expression_voice_prompt_chunks.md"
        image_scene_file = "ai_manga_image_scene_prompt_chunks.md"

        matched_priority_files: list[str] = []
        is_three_view_request = self._is_character_three_view_request(question) or any(
            keyword in question for keyword in three_view_keywords
        )
        if three_view_file in target_files and is_three_view_request:
            matched_priority_files.append(three_view_file)
        if expression_file in target_files and self._is_expression_voice_request(question) and not is_three_view_request:
            matched_priority_files.append(expression_file)
        if image_scene_file in target_files and self._is_scene_or_image_prompt_request(question):
            matched_priority_files.append(image_scene_file)
        if matched_priority_files:
            return matched_priority_files

        rules = [
            (
                "ai_video_action_naturalization_chunks.md",
                ("动作", "走路", "行走", "步态", "转身", "回头", "抬头", "低头", "伸手", "僵硬", "机器人", "互动", "对视"),
            ),
            (
                "ai_video_style_aesthetics_chunks.md",
                ("风格", "美学", "画风", "二次元", "动漫", "动画", "漫剧", "吉卜力", "新海诚", "赛博朋克", "水墨", "Webtoon", "皮克斯", "迪士尼"),
            ),
            (
                "ai_video_character_design_chunks.md",
                ("角色", "人物设定", "设定卡", "一致", "像换人", "换场景", "脸型", "发型", "服装", "参考图", "多角度", "图生图"),
            ),
            (
                "ai_video_script_structure_chunks.md",
                ("剧本", "脚本", "分镜", "分场景", "JSON", "json", "episode", "scene", "duration", "对接", "故事大纲"),
            ),
            (
                image_scene_file,
                ("图片生成", "图片分析", "场景提示词", "视觉色卡", "色卡", "色调", "光影", "构图"),
            ),
            (
                expression_file,
                ("表情", "语气", "台词", "眼神", "眉毛", "嘴角", "面部细节", "微表情"),
            ),
        ]

        narrowed: list[str] = []
        for file_name, keywords in rules:
            if file_name not in target_files:
                continue
            if any(keyword in question for keyword in keywords):
                narrowed.append(file_name)

        return narrowed or target_files

    def _filter_grounding_docs(self, question: str, docs: list[Document]) -> list[Document]:
        """过滤掉宽泛规则块，只保留更适合作为回答依据的知识块。"""
        if not docs:
            return []

        question_text = question.lower()
        allow_faq = any(
            keyword in question
            for keyword in ("幅度", "速度", "现代", "镜头", "情绪", "表情")
        )

        preferred: list[Document] = []
        fallback: list[Document] = []

        for doc in docs:
            metadata = doc.metadata or {}
            file_name = str(metadata.get("_file_name", ""))
            title_text = " ".join(
                str(metadata.get(key, ""))
                for key in ("h1", "h2", "h3", "chunk_title", "_file_name")
            )
            content = doc.page_content or ""
            combined = f"{title_text}\n{content}"

            is_catalog_doc = file_name == CATALOG_FILE_NAME
            is_rule_doc = "Agent 规则" in combined or "回答规则" in title_text
            is_scope_doc = "文档用途与适用场景" in combined
            is_answer_format_doc = "标准输出格式" in combined
            is_faq_doc = "常见问题与回答" in combined

            if is_catalog_doc:
                fallback.append(doc)
                continue
            if is_rule_doc or is_scope_doc or is_answer_format_doc:
                fallback.append(doc)
                continue
            if is_faq_doc and not allow_faq:
                fallback.append(doc)
                continue

            preferred.append(doc)

        selected = preferred or fallback
        if "走路" in question_text or "步态" in question:
            selected = sorted(
                selected,
                key=lambda doc: 0 if "步态写法" in (doc.page_content or "") else 1,
            )

        return selected[:3]

    def _doc_source_label(self, doc: Document, index: int) -> str:
        metadata = doc.metadata or {}
        headers = [
            str(metadata[key])
            for key in ("h1", "h2", "h3", "chunk_title")
            if metadata.get(key)
        ]
        title = " > ".join(headers) if headers else f"参考资料 {index}"
        chunk_id = metadata.get("chunk_id")
        suffix = f" / {chunk_id}" if chunk_id else ""
        return f"{title}{suffix}"

    def _grounded_docs_signature(self, docs: list[Document]) -> str:
        if not docs:
            return "empty"

        parts: list[str] = []
        for doc in docs:
            metadata = doc.metadata or {}
            parts.append(
                "|".join(
                    [
                        str(metadata.get("_file_name") or ""),
                        str(metadata.get("chunk_id") or ""),
                        str(metadata.get("h2") or metadata.get("chunk_title") or ""),
                        str(len(doc.page_content or "")),
                    ]
                )
            )
        return "||".join(parts)

    def _format_grounding_context(self, docs: list[Document]) -> str:
        if not docs:
            return (
                "未检索到可用知识库片段。回答时必须明确说明知识库未命中，"
                "不得把创作建议伪装成知识库事实。"
            )

        parts = []
        for i, doc in enumerate(docs, 1):
            content = (doc.page_content or "").strip()
            if len(content) > 1600:
                content = f"{content[:1600]}..."
            parts.append(
                f"【资料 {i}】{self._doc_source_label(doc, i)}\n"
                f"{content}"
            )
        return "\n\n".join(parts)

    def _serialize_grounding_docs(self, docs: list[Document]) -> list[dict[str, Any]]:
        serialized = []
        for i, doc in enumerate(docs, 1):
            metadata = doc.metadata or {}
            serialized.append(
                {
                    "index": i,
                    "title": self._doc_source_label(doc, i),
                    "chunkId": metadata.get("chunk_id"),
                    "contentType": metadata.get("content_type"),
                    "preview": (doc.page_content or "").strip()[:240],
                }
            )
        return serialized

    def _is_model_identity_request(self, question: str) -> bool:
        """识别用户询问当前 AI/模型配置的请求，避免让模型自行猜测。"""
        q = question.strip().lower()
        if not q:
            return False

        explicit_config_terms = (
            "rag_model",
            "dashscope_model",
            "dasHSCOPE_MODEL".lower(),
            "当前模型配置",
            "模型配置",
        )
        if any(term in q for term in explicit_config_terms):
            return True

        model_terms = ("模型", "大模型", "model")
        ask_terms = (
            "你用",
            "你是用",
            "你现在用",
            "你正在用",
            "当前用",
            "当前使用",
            "现在使用",
            "正在用",
            "使用的",
            "使用的是",
            "用的是",
            "是什么",
            "哪个",
            "哪一个",
            "什么",
            "啥",
        )
        if any(term in q for term in model_terms) and any(term in q for term in ask_terms):
            return True

        ai_identity_patterns = (
            "什么ai",
            "什么 ai",
            "哪个ai",
            "哪个 ai",
            "哪一个ai",
            "哪一个 ai",
            "用的ai",
            "用的 ai",
            "用的是ai",
            "用的是 ai",
            "使用的ai",
            "使用的 ai",
            "使用的是ai",
            "使用的是 ai",
            "ai模型",
            "ai model",
        )
        return any(pattern in q for pattern in ai_identity_patterns)

    def _build_model_identity_answer(self, model_name: str | None = None) -> str:
        active_model = self._normalize_model_name(model_name)
        rag_model = config.rag_model or "未配置"
        dashscope_model = config.dashscope_model or "未配置"
        if active_model == rag_model:
            summary = f"我当前对话/RAG 使用的模型是 `{active_model}`。"
        else:
            summary = f"我当前这次对话请求使用的是 `{active_model}`，RAG 默认模型配置是 `{rag_model}`。"

        return (
            f"{summary}\n\n"
            f"- `当前请求模型`: `{active_model}`\n"
            f"- `RAG_MODEL`: `{rag_model}`\n"
            f"- `DASHSCOPE_MODEL`: `{dashscope_model}`\n\n"
            "`RAG_MODEL` 是当前聊天/RAG Agent 实际使用的模型；"
            "`DASHSCOPE_MODEL` 是 DashScope 通用默认模型配置，其他服务可能会引用它。"
        )

    def _classify_sensitive_info_request(self, question: str) -> str | None:
        """识别索取系统秘密或他人隐私的请求；安全防护建议类问题不拦截。"""
        q = question.strip()
        if not q:
            return None

        normalized = q.lower()
        secret_terms = (
            "api key",
            "apikey",
            "api_key",
            "secret",
            "token",
            "password",
            "passwd",
            "credential",
            "credentials",
            "private key",
            "database_url",
            "db_password",
            "openai_api_key",
            "dashscope_api_key",
            "alibaba_cloud_access_key_secret",
            "aliyun_sms_access_key_secret",
            "auth_secret_key",
            ".env",
            "环境变量",
            "系统密钥",
            "系统秘钥",
            "密钥",
            "秘钥",
            "私钥",
            "凭据",
            "密码",
            "连接串",
            "数据库连接",
            "cookie",
            "session",
            "会话令牌",
            "访问令牌",
        )
        pii_terms = (
            "手机号",
            "手机号码",
            "电话号码",
            "身份证",
            "邮箱",
            "电子邮件",
            "用户信息",
            "用户资料",
            "账号信息",
            "账户信息",
            "聊天记录",
            "登录记录",
            "实名信息",
            "个人信息",
            "隐私数据",
        )
        disclosure_actions = (
            "给我",
            "发我",
            "告诉我",
            "显示",
            "展示",
            "查看",
            "查一下",
            "查询",
            "列出",
            "导出",
            "打印",
            "读取",
            "复制",
            "获取",
            "提取",
            "拿到",
            "发出来",
            "是什么",
            "是多少",
            "show",
            "reveal",
            "print",
            "dump",
            "export",
            "list",
            "read",
            "fetch",
            "get",
        )
        protected_subjects = (
            "其他人",
            "别人",
            "他人",
            "所有用户",
            "全部用户",
            "全量用户",
            "某个用户",
            "任意用户",
            "用户表",
            "后台用户",
            "管理员",
            "同事",
            "客户",
        )
        safe_guidance_terms = (
            "如何保护",
            "怎么保护",
            "怎样保护",
            "如何防止",
            "怎么防止",
            "如何避免",
            "怎么避免",
            "如何脱敏",
            "怎么脱敏",
            "如何轮换",
            "怎么轮换",
            "安全方案",
            "权限控制",
            "访问控制",
            "审计",
            "最佳实践",
            "风险",
            "加密",
            "泄露排查",
            "是否泄露",
        )

        has_secret = any(term in normalized for term in secret_terms)
        asks_to_disclose = any(action in normalized for action in disclosure_actions)
        if has_secret and asks_to_disclose:
            return "secret_disclosure"

        classification_text = q
        if "【剧本引用提示词生成任务】" in classification_text:
            classification_text = classification_text.split("【剧本引用片段】", 1)[0]
            classification_text = classification_text.replace("原始需求：", "")
        normalized = classification_text.lower()

        has_pii = any(term in normalized for term in pii_terms)
        asks_to_disclose = any(action in normalized for action in disclosure_actions)
        targets_other_or_bulk = any(subject in normalized for subject in protected_subjects)
        asks_for_safe_guidance = any(term in normalized for term in safe_guidance_terms)

        if has_pii and (targets_other_or_bulk or asks_to_disclose):
            return "pii_disclosure"
        if targets_other_or_bulk and asks_to_disclose and any(
            term in normalized for term in ("用户", "账号", "账户", "资料", "信息", "记录", "数据")
        ):
            return "user_data_disclosure"

        if asks_for_safe_guidance:
            return None
        return None

    def _build_sensitive_refusal(self, category: str | None = None) -> str:
        return (
            "抱歉，我不能提供系统 API Key、Secret、Token、密码、数据库连接串、"
            "环境变量值、管理员凭据、他人手机号、账号信息、聊天记录或其他隐私数据。\n\n"
            "如果你是在做安全排查，我可以帮你：\n"
            "- 检查配置是否存在泄露风险\n"
            "- 设计密钥轮换和权限控制方案\n"
            "- 给出日志脱敏、手机号脱敏和访问审计方案\n"
            "- 帮你写安全拦截规则或测试用例"
        )

    def _infer_prompt_section_title(self, question: str, docs: list[Document] | None = None) -> str:
        """根据用户问题给提示词区块一个强制标题，避免泛问被误标为优化后提示词。"""
        q = question.strip()
        explicit_template = self._explicit_prompt_template(q)
        explicit_titles = {
            "character": "【示例提示词：人物三视图设定卡】",
            "scene": "【示例提示词：场景画面设定】",
            "expression": "【示例提示词：表情语气细化】",
            "storyboard": "【示例提示词：分镜脚本】",
            "plot": "【示例提示词：剧情结构设计】",
        }
        if explicit_template in explicit_titles:
            return explicit_titles[explicit_template]

        rewrite_markers = (
            "原提示词",
            "原始提示词",
            "提示词：",
            "提示词:",
            "prompt:",
            "PROMPT:",
            "帮我改",
            "帮我优化这",
            "优化下面",
            "改写",
            "润色",
        )
        if any(marker in q for marker in rewrite_markers) and len(q) >= 16:
            return "【优化后提示词】"

        if self._is_character_three_view_request(q, docs) or any(word in q for word in ("角色提示词导演", "角色一句话", "外貌识别")):
            return "【示例提示词：人物三视图设定卡】"
        if self._is_expression_voice_request(q) or any(word in q for word in ("表情提示词专家", "情绪拆解")):
            return "【示例提示词：表情语气细化】"
        if self._is_scene_or_image_prompt_request(q, docs) or any(word in q for word in ("场景提示词专家", "场景拆解", "空间结构", "光影氛围")):
            return "【示例提示词：场景画面设定】"
        if any(word in q for word in ("剧情策划", "剧情提示词", "剧情核心", "起承转合", "冲突设计", "结尾钩子")):
            return "【示例提示词：剧情结构设计】"
        if any(word in q for word in ("分镜导演", "分镜脚本", "镜号", "景别", "镜头角度/运动", "Markdown 表格")):
            return "【示例提示词：分镜脚本】"
        file_names = {
            str((doc.metadata or {}).get("_file_name") or "")
            for doc in (docs or [])
        }
        if "ai_video_character_design_chunks.md" in file_names:
            if any(word in q for word in ("一致", "像换人", "不变", "参考图", "多角度", "侧面", "背面")):
                return "【示例提示词：角色一致性设定】"
            return "【示例提示词：人物三视图设定卡】"
        if "ai_manga_expression_voice_prompt_chunks.md" in file_names:
            return "【示例提示词：表情语气细化】"
        if "ai_manga_image_scene_prompt_chunks.md" in file_names:
            return "【示例提示词：场景画面设定】"
        if "ai_video_style_aesthetics_chunks.md" in file_names:
            return "【示例提示词：视频风格设定】"
        if "ai_video_script_structure_chunks.md" in file_names:
            if any(word in q for word in ("分镜", "镜号", "景别", "镜头运动", "JSON", "json", "对接")):
                return "【示例提示词：剧本结构化生成】"
            return "【示例提示词：剧情结构设计】"

        if any(word in q for word in ("哭泣", "悲伤", "愤怒", "生气", "强装平静", "震惊")) and not any(word in q for word in ("走路", "行走", "转身", "回头", "互动", "对视")):
            return "【示例提示词：表情语气细化】"

        if any(word in q for word in ("走路", "行走", "步态")):
            return "【示例提示词：人物自然走路优化】"
        if "抬头" in q:
            return "【示例提示词：人物抬头动作优化】"
        if "转身" in q or "回头" in q:
            return "【示例提示词：人物转身回头动作优化】"
        if "多人" in q or "对视" in q or "互动" in q:
            return "【示例提示词：多人互动动作优化】"
        return "【示例提示词：视频提示词示例】"

    def _build_grounded_user_prompt(self, question: str, docs: list[Document]) -> str:
        prompt, _ = self._build_grounded_user_prompt_with_meta(question, docs)
        return prompt

    def _build_grounded_user_prompt_with_meta(
        self,
        question: str,
        docs: list[Document],
        *,
        cache_key: str | None = None,
        log_hit: bool = True,
    ) -> tuple[str, bool]:
        cache_key = cache_key or self._normalize_grounding_cache_key(question)
        docs_signature = self._grounded_docs_signature(docs)
        cached_prompt = self._get_cached_grounded_prompt(
            cache_key,
            docs_signature=docs_signature,
            log_hit=log_hit,
        )
        if cached_prompt is not None:
            return cached_prompt, True

        grounding_context = self._format_grounding_context(docs)
        prompt_section_title = self._infer_prompt_section_title(question, docs)
        is_character_prompt = self._is_character_three_view_request(question, docs)
        is_expression_prompt = self._is_expression_voice_request(question) and not is_character_prompt
        is_scene_prompt = self._is_scene_or_image_prompt_request(question, docs) and not is_character_prompt
        needs_real_skin = (
            self._explicit_real_skin_request_for_character(question)
            if is_character_prompt
            else self._mentions_real_skin_request(question)
        )

        extra_contracts: list[str] = [
            "- 可复制提示词区块必须自包含，并含“正向提示词”和“负面提示词”。\n"
        ]
        if is_character_prompt:
            skin_rule = (
                "如用户明确要求禁塑料感、真人感或写实皮肤，可在正向提示词末尾加入简短真实皮肤词；"
                if needs_real_skin
                else "不得默认加入活人感、毛孔、皮肤微纹理、痘印、油光等皮肤细节板块；"
            )
            extra_contracts.append(
                "- 人物/三视图：单张纯白人物卡；左 1/3 超大正脸，右 2/3 正/侧/后完整全身；自然站姿、无动作表情、无道具背景、无裁切。"
                "先写记忆点和视觉锚点；不要输出旧模板板块。"
                "负面词排除文字水印、缺脚、视图不全、脸/发型/服装不一致、道具武器、背景、夸张动作表情。"
                f"{skin_rule}\n"
            )
        if is_expression_prompt:
            extra_contracts.append(
                "- 表情语气：只写脸部和声音表达；不默认写全身动作、走位、手势、道具或动作链。\n"
            )
        if is_scene_prompt:
            extra_contracts.append(
                "- 场景画面：色调可作为文字方案；除非用户要求，不让画面出现色卡块或文字说明。\n"
            )

        prompt = (
            f"用户原始问题：\n{question}\n\n"
            f"【服务端强制知识库检索结果】\n{grounding_context}\n\n"
            f"【本次提示词区块强制标题】\n{prompt_section_title}\n\n"
            "【强制回答约束】\n"
            "1. 【知识库依据】只列实际使用的 1-2 条；未命中则说明无直接依据并标为创作建议。\n"
            "2. 不编造知识库没有的结论、案例、参数或规则。\n"
            f"3. 最终提示词只输出一份，标题逐字使用：{prompt_section_title}。\n"
            "4. 默认中文；剧情类不默认拆分镜；提示词用自然语言多行分段。\n"
            "5. 末尾用【回答自检】检查完整性、依据真实性和待补充信息。\n"
            f"{''.join(extra_contracts)}"
        )
        self._store_grounded_prompt_cache(cache_key, prompt, docs_signature)
        return prompt, False

    async def query(
        self,
        question: str,
        session_id: str,
        model_name: str | None = None,
    ) -> str:
        """
        非流式处理用户问题（一次性返回完整答案）

        Args:
            question: 用户问题
            session_id: 会话ID（作为 thread_id）

        Returns:
            str: 完整答案
        """
        try:
            selected_model = self._normalize_model_name(model_name)
            request_started_at = perf_counter()
            sensitive_category = self._classify_sensitive_info_request(question)
            if sensitive_category:
                logger.warning(
                    f"[会话 {session_id}] 拦截敏感信息请求: category={sensitive_category}, length={len(question)}"
                )
                return self._build_sensitive_refusal(sensitive_category)

            if self._is_model_identity_request(question):
                logger.info(f"[会话 {session_id}] 命中模型配置查询，直接返回当前模型配置: model={selected_model}")
                return self._build_model_identity_answer(selected_model)

            init_started_at = perf_counter()
            selected_model = await self._initialize_agent(selected_model)
            agent = self._agents[selected_model]
            init_elapsed_ms = (perf_counter() - init_started_at) * 1000

            logger.info(f"[会话 {session_id}] RAG Agent 收到查询（非流式）: model={selected_model}, {question}")

            grounding_started_at = perf_counter()
            grounding_metrics = self._collect_grounding_metrics(question)
            grounding_docs = grounding_metrics["docs"]
            grounded_question = grounding_metrics["grounded_question"]
            grounding_elapsed_ms = (perf_counter() - grounding_started_at) * 1000

            # 构建消息列表（系统提示 + 服务端检索增强后的用户问题）
            messages = [
                SystemMessage(content=self._get_system_prompt()),
                HumanMessage(content=grounded_question)
            ]

            # 构建 Agent 输入
            agent_input = {"messages": messages}

            # 配置 thread_id（用于会话持久化）
            config_dict = {
                "configurable": {
                    "thread_id": session_id
                }
            }

            invoke_started_at = perf_counter()
            result = await agent.ainvoke(
                input=agent_input,
                config=config_dict,
            )
            invoke_elapsed_ms = (perf_counter() - invoke_started_at) * 1000

            # 提取最终答案
            messages_result = result.get("messages", [])
            if messages_result:
                last_message = messages_result[-1]
                answer = last_message.content if hasattr(last_message, 'content') else str(last_message)

                # 记录工具调用
                if hasattr(last_message, "tool_calls") and last_message.tool_calls:
                    tool_names = [tc.get("name", "unknown") for tc in last_message.tool_calls]
                    logger.info(f"[会话 {session_id}] Agent 调用了工具: {tool_names}")

                logger.info(
                    f"[会话 {session_id}] RAG Agent 查询完成（非流式）: "
                    f"model={selected_model}, "
                    f"{self._format_grounding_metrics_summary(doc_cache_hit=grounding_metrics['doc_cache_hit'], prompt_cache_hit=grounding_metrics['prompt_cache_hit'], docs_count=len(grounding_docs))}, "
                    f"init={init_elapsed_ms:.1f}ms, grounding={grounding_elapsed_ms:.1f}ms, "
                    f"invoke={invoke_elapsed_ms:.1f}ms, total={(perf_counter() - request_started_at) * 1000:.1f}ms, "
                    f"answer_chars={len(answer)}"
                )
                return answer

            logger.warning(f"[会话 {session_id}] Agent 返回结果为空")
            return ""

        except Exception as e:
            logger.error(f"[会话 {session_id}] RAG Agent 查询失败（非流式）: {e}")
            raise

    async def query_stream(
        self,
        question: str,
        session_id: str,
        model_name: str | None = None,
        emit_auxiliary_events: bool = False,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        流式处理用户问题（逐步返回答案片段）

        Args:
            question: 用户问题
            session_id: 会话ID（作为 thread_id）
            emit_auxiliary_events: 是否输出辅助调试/检索事件

        Yields:
            Dict[str, Any]: 包含流式数据的字典
                - type: "content" | "tool_call" | "complete" | "error"
                - data: 具体内容
        """
        try:
            selected_model = self._normalize_model_name(model_name)
            request_started_at = perf_counter()
            sensitive_category = self._classify_sensitive_info_request(question)
            if sensitive_category:
                logger.warning(
                    f"[会话 {session_id}] 拦截敏感信息请求（流式）: category={sensitive_category}, length={len(question)}"
                )
                answer = self._build_sensitive_refusal(sensitive_category)
                if emit_auxiliary_events:
                    yield {
                        "type": "search_results",
                        "data": [],
                    }
                yield {
                    "type": "content",
                    "data": answer,
                    "node": "sensitive_info_guard",
                }
                yield {
                    "type": "complete",
                    "data": {"answer": answer},
                }
                return

            if self._is_model_identity_request(question):
                logger.info(f"[会话 {session_id}] 命中模型配置查询（流式），直接返回当前模型配置: model={selected_model}")
                answer = self._build_model_identity_answer(selected_model)
                if emit_auxiliary_events:
                    yield {
                        "type": "search_results",
                        "data": [],
                    }
                yield {
                    "type": "content",
                    "data": answer,
                    "node": "model_identity",
                }
                yield {
                    "type": "complete",
                    "data": {"answer": answer},
                }
                return

            init_started_at = perf_counter()
            selected_model = await self._initialize_agent(selected_model)
            agent = self._agents[selected_model]
            init_elapsed_ms = (perf_counter() - init_started_at) * 1000

            logger.info(f"[会话 {session_id}] RAG Agent 收到查询（流式）: model={selected_model}, {question}")

            grounding_started_at = perf_counter()
            grounding_metrics = self._collect_grounding_metrics(question)
            grounding_docs = grounding_metrics["docs"]
            grounded_question = grounding_metrics["grounded_question"]
            grounding_elapsed_ms = (perf_counter() - grounding_started_at) * 1000

            if emit_auxiliary_events:
                yield {
                    "type": "search_results",
                    "data": self._serialize_grounding_docs(grounding_docs),
                }

            # 构建消息列表（系统提示 + 服务端检索增强后的用户问题）
            messages = [
                SystemMessage(content=self._get_system_prompt()),
                HumanMessage(content=grounded_question)
            ]

            # 构建 Agent 输入
            agent_input = {"messages": messages}

            # 配置 thread_id（用于会话持久化）
            config_dict = {
                "configurable": {
                    "thread_id": session_id
                }
            }

            answer_chunks: list[str] = []
            answer_char_count = 0
            stream_started_at = perf_counter()
            first_token_elapsed_ms: float | None = None
            first_reasoning_elapsed_ms: float | None = None
            reasoning_char_count = 0

            async for token, metadata in agent.astream(
                input=agent_input,
                config=config_dict,
                stream_mode="messages",
            ):
                node_name = metadata.get('langgraph_node', 'unknown') if isinstance(metadata, dict) else 'unknown'
                message_type = type(token).__name__

                if message_type in ("AIMessage", "AIMessageChunk"):
                    additional_kwargs = getattr(token, "additional_kwargs", {}) or {}
                    reasoning_content = (
                        additional_kwargs.get("reasoning_content", "")
                        if isinstance(additional_kwargs, dict)
                        else ""
                    )
                    if reasoning_content:
                        if first_reasoning_elapsed_ms is None:
                            first_reasoning_elapsed_ms = (
                                perf_counter() - stream_started_at
                            ) * 1000
                        reasoning_char_count += len(str(reasoning_content))

                    content_blocks = getattr(token, 'content_blocks', None)

                    if content_blocks and isinstance(content_blocks, list):
                        for block in content_blocks:
                            if isinstance(block, dict) and block.get('type') == 'text':
                                text_content = block.get('text', '')
                                if text_content:
                                    if first_token_elapsed_ms is None:
                                        first_token_elapsed_ms = (
                                            perf_counter() - stream_started_at
                                        ) * 1000
                                    answer_chunks.append(text_content)
                                    answer_char_count += len(text_content)
                                    yield {
                                        "type": "content",
                                        "data": text_content,
                                        "node": node_name
                                    }

            answer = "".join(answer_chunks)
            logger.info(
                f"[会话 {session_id}] RAG Agent 查询完成（流式）: "
                f"model={selected_model}, "
                f"{self._format_grounding_metrics_summary(doc_cache_hit=grounding_metrics['doc_cache_hit'], prompt_cache_hit=grounding_metrics['prompt_cache_hit'], docs_count=len(grounding_docs))}, "
                f"init={init_elapsed_ms:.1f}ms, grounding={grounding_elapsed_ms:.1f}ms, "
                f"first_reasoning={first_reasoning_elapsed_ms or 0:.1f}ms, "
                f"first_token={first_token_elapsed_ms or 0:.1f}ms, "
                f"stream={(perf_counter() - stream_started_at) * 1000:.1f}ms, "
                f"total={(perf_counter() - request_started_at) * 1000:.1f}ms, "
                f"answer_chars={answer_char_count}, reasoning_chars={reasoning_char_count}"
            )
            yield {
                "type": "complete",
                "data": {"answer": answer},
            }

        except Exception as e:
            logger.error(f"[会话 {session_id}] RAG Agent 查询失败（流式）: {e}")
            yield {
                "type": "error",
                "data": str(e)
            }
            raise

    def get_session_history(self, session_id: str) -> list:
        """
        获取会话历史（从 MemorySaver checkpointer 中读取）

        Args:
            session_id: 会话ID（即 thread_id）

        Returns:
            list: 消息历史列表 [{"role": "user|assistant", "content": "...", "timestamp": "..."}]
        """
        try:
            # 使用 checkpointer 的 get 方法获取最新的检查点
            config = {"configurable": {"thread_id": session_id}}
            
            # 获取该 thread 的最新检查点
            checkpoint_tuple = self.checkpointer.get(config)
            
            if not checkpoint_tuple:
                logger.info(f"获取会话历史: {session_id}, 消息数量: 0")
                return []
            
            # checkpoint_tuple 可能是命名元组或普通元组，安全地提取 checkpoint
            # 通常第一个元素是 checkpoint 数据
            if hasattr(checkpoint_tuple, 'checkpoint'):
                checkpoint_data = checkpoint_tuple.checkpoint  # type: ignore
            else:
                # 如果是普通元组，第一个元素是 checkpoint
                checkpoint_data = checkpoint_tuple[0] if checkpoint_tuple else {}
            
            # 从检查点中提取消息
            messages = checkpoint_data.get("channel_values", {}).get("messages", [])
            
            # 转换为前端需要的格式
            history = []
            for msg in messages:
                # 跳过系统消息
                if isinstance(msg, SystemMessage):
                    continue
                    
                role = "user" if isinstance(msg, HumanMessage) else "assistant"
                content = msg.content if hasattr(msg, 'content') else str(msg)
                
                # 提取时间戳（如果有的话）
                timestamp = getattr(msg, 'timestamp', None)
                if timestamp:
                    history.append({
                        "role": role,
                        "content": content,
                        "timestamp": timestamp
                    })
                else:
                    from datetime import datetime
                    history.append({
                        "role": role,
                        "content": content,
                        "timestamp": datetime.now().isoformat()
                    })
            
            logger.info(f"获取会话历史: {session_id}, 消息数量: {len(history)}")
            return history
            
        except Exception as e:
            logger.error(f"获取会话历史失败: {session_id}, 错误: {e}")
            return []

    def clear_session(self, session_id: str) -> bool:
        """
        清空会话历史（从 MemorySaver checkpointer 中删除）

        Args:
            session_id: 会话ID（即 thread_id）

        Returns:
            bool: 是否成功
        """
        try:
            # 使用 checkpointer 的 delete_thread 方法删除该 thread 的所有检查点
            self.checkpointer.delete_thread(session_id)
            
            logger.info(f"已清除会话历史: {session_id}")
            return True
            
        except Exception as e:
            logger.error(f"清空会话历史失败: {session_id}, 错误: {e}")
            return False

    async def cleanup(self):
        """清理资源"""
        try:
            logger.info("清理 RAG Agent 服务资源...")
            logger.info("RAG Agent 服务资源已清理")
        except Exception as e:
            logger.error(f"清理资源失败: {e}")


# 全局单例 - 启用流式输出
rag_agent_service = RagAgentService(streaming=True)
