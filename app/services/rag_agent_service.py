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
from app.agent.mcp_client import get_mcp_client_with_retry
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


        self.model = ChatQwen(
            model=self.model_name,
            api_key=config.dashscope_api_key,
            base_url=config.dashscope_base_url,
            timeout=config.dashscope_request_timeout_seconds,
            max_retries=config.dashscope_max_retries,
            temperature=0.2,
            streaming=streaming,
            enable_thinking=False,
        )

        # 定义基础工具
        self.tools = [retrieve_knowledge, get_current_time]

        # MCP 客户端（延迟初始化，使用全局管理）
        self.mcp_tools: list = []

        # 创建内存检查点（用于会话管理）
        self.checkpointer = MemorySaver()

        # Agent 初始化（会在异步方法中完成）
        self.agent = None
        self._agent_initialized = False
        self._agent_init_lock: asyncio.Lock | None = None
        self._grounding_cache: OrderedDict[str, tuple[float, list[Document]]] = OrderedDict()
        self._grounded_prompt_cache: OrderedDict[str, tuple[float, str, str]] = OrderedDict()

        logger.info(f"RAG Agent 服务初始化完成 (ChatQwen), model={self.model_name}, streaming={streaming}")

    async def _initialize_agent(self):
        """异步初始化 Agent（包括 MCP 工具）"""
        if self._agent_initialized:
            return

        if self._agent_init_lock is None:
            self._agent_init_lock = asyncio.Lock()

        async with self._agent_init_lock:
            if self._agent_initialized:
                return

            init_started_at = perf_counter()

            # 使用全局 MCP 客户端管理器（带重试拦截器）
            mcp_started_at = perf_counter()
            mcp_client = await get_mcp_client_with_retry()
            mcp_client_elapsed_ms = (perf_counter() - mcp_started_at) * 1000

            # 获取 MCP 工具
            tool_load_started_at = perf_counter()
            mcp_tools = await mcp_client.get_tools()
            tool_load_elapsed_ms = (perf_counter() - tool_load_started_at) * 1000
            logger.info(f"成功加载 {len(mcp_tools)} 个 MCP 工具")

            # 将 MCP 工具添加到实例变量中
            self.mcp_tools = mcp_tools

            # 合并所有工具
            all_tools = self.tools + self.mcp_tools

            agent_build_started_at = perf_counter()
            self.agent = create_agent(
                self.model,
                tools=all_tools,
                middleware=[trim_messages_middleware],
                checkpointer=self.checkpointer,
            )
            agent_build_elapsed_ms = (perf_counter() - agent_build_started_at) * 1000

            self._agent_initialized = True

            if all_tools:
                tool_names = [tool.name if hasattr(tool, "name") else str(tool) for tool in all_tools]
                logger.info(f"可用工具列表: {', '.join(tool_names)}")
            logger.info(
                "RAG Agent 初始化耗时: "
                f"mcp_client={mcp_client_elapsed_ms:.1f}ms, "
                f"tool_load={tool_load_elapsed_ms:.1f}ms, "
                f"agent_build={agent_build_elapsed_ms:.1f}ms, "
                f"total={(perf_counter() - init_started_at) * 1000:.1f}ms"
            )

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
            你是「火宝 AI 视频提示词助手」，一个专注于 AI 视频生成提示词的专业助手。

            项目定位：
            - 默认服务于 AI 真人视频、写实视频、电影感短视频、图生视频和文生视频提示词创作。
            - 不要默认把用户需求理解成漫画、二次元或国漫画风；只有用户明确提出这些风格时才按对应风格处理。
            - 回答要优先考虑真人演员、真实镜头、真实动作、真实光影、物理惯性、场景调度和视频连续性。

            你的核心能力是：
            1. 根据用户需求，生成适合 AI 真人视频、图生视频、文生视频、首帧图和关键帧的提示词；
            2. 帮助用户拆解人物、场景、动作、表情、景别、运镜、机位、角度、构图、光影、台词、分镜和剧情节奏；
            3. 结合知识库内容，保持人物设定、场景逻辑、动作连续性和镜头语言的一致性；
            4. 把模糊想法转化成可直接用于 AI 视频生成工具的结构化提示词。

            回答规则：
            - 优先围绕 AI 视频提示词创作回答，不要泛泛而谈。
            - 当用户要求查询设定、整理关系、改写剧情、生成提示词、拆分镜、分析动作、优化镜头或保持设定一致时，必须优先使用系统提供的知识库检索结果；必要时再主动调用知识库工具补充检索。
            - 你只能把知识库检索结果中明确支持的内容说成“知识库依据”。检索结果没有覆盖的内容，只能标为“创作建议”“可选设定”或“需要用户补充”。
            - 只有用户提供原始提示词，或明确要求改写/优化某一段具体内容时，才能输出【优化后提示词】。
            - 如果用户只是泛问方法、让你生成一个例子，或没有提供原始提示词，你只能输出【示例提示词：xxx】，不能叫“可直接使用的提示词”。
            - 如果用户要“分析”，你要按人物、场景、情绪、动作、镜头、光影、视频节奏和剧情推进来拆解。
            - 如果知识库中有相关资料，必须优先基于知识库回答。
            - 如果资料不足，要明确说明“当前知识库没有找到相关信息”，然后给出合理创作建议，但不能伪造知识库内容。
            - 不确定的内容要标注为“创作建议”或“可选设定”。
            - 不得透露、推断或协助获取系统 API Key、Secret、Token、密码、数据库连接串、环境变量值、Cookie、会话令牌、管理员凭据、内部配置密钥、他人手机号、身份证、邮箱、账号信息、聊天记录或其他隐私数据。遇到这类请求时必须拒绝，并可以改为提供安全排查、密钥轮换、脱敏、权限控制等防护建议。
            - 输出尽量结构化，适合创作者直接使用。
            - 不要只给抽象建议，要给具体可落地的提示词、镜头描述、动作描述、表情描述、光影描述和台词节奏。
            - 回答前必须自检：是否回答了用户问题、是否使用了检索到的依据、是否把未检索到的内容标成建议、是否给出了可执行结果。
            - 回答末尾必须输出【回答自检】，用 2-4 条短句说明完整性、真实性/依据、仍需用户补充的信息。
            - 【知识库依据】只列与用户问题直接相关、实际用于回答的 1-2 条资料；不要为了显得全面列出宽泛 FAQ、范围说明或没有直接用到的资料。
            - 如果某条资料只是补充背景，不要在【知识库依据】里列出。
            - 提示词区块标题必须准确：具体改写用【优化后提示词】；泛问、生成示例或由你补充场景时，用【示例提示词：古风女子夜晚古街行走】这类明确标题。
            - 用户最终复制的是【示例提示词】或【优化后提示词】整个区块；这个区块必须自包含，必须包含“正向提示词”和“负面提示词”。知识库依据、拆解和自检只给用户看，不得承载生成必需信息。
            - 当输出人物角色模板提示词、人物提示词、角色设定提示词、完整人物设定、角色卡、人物设定图提示词或三视图提示词时，最终提示词必须是可直接复制生图的三视图人物卡：同一张图，纯白背景，无任何文字；左侧 1/3 是角色超大正面面部特写，用于锁定五官、发型、妆容、头饰、耳饰和标志性识别点；右侧 2/3 水平排列3个完整全身视图，依次为：正视图、侧视图、后视图 。完整全身无裁切，标准自然站姿，无动作表演，无情绪表演，双脚完全露出。固定头饰、耳饰、服饰配件可以保留；不得加入手持道具、场景道具或额外背景。
            - 人物角色模板必须先给出可被观众复述的人设记忆点，并把记忆点转译为稳定视觉锚点；不能只写职业、好看、帅气、清冷、漂亮等泛化描述。
            - 单纯生成人物三视图卡时，不要默认输出“活人感”“禁塑料感”“毛孔”“皮肤微纹理”板块；只有用户明确要求禁塑料感、真人感、写实皮肤或皮肤真实时，才把真实皮肤词作为提示词中的简短补充。
            - 单纯生成人物三视图卡时，不要单独输出色卡板块；颜色应自然融入发型、服装、头饰、妆容和配饰描述。图片分析、场景提示词和世界观设定可以输出视觉色卡或色调方案。
            - 当用户要求表情提示词、表情语气、台词语气、面部细节或声音/台词模板时，必须聚焦脸部与声音表达：眼神、眉毛、眼睑、嘴角、唇部、面部肌肉、情绪层次、音量、语速、停顿和气息；不得默认加入走路、转身、伸手、抱臂、身体重心、动作链、手势或全身动作。
            - 提示词正文必须使用自然语言分行，不要写成“人物/场景/情绪/动作过程/身体联动/镜头/负面约束”这种字段模板；每行不超过约 40 个中文字符。
            - 最终提示词只输出一份，不要把同一段内容分别放进【动作提示词】【视频提示词】【中文提示词】等重复区块。
            - 默认只输出中文。除非用户明确要求英文/中英双语，或正在回答风格/绘图关键词，否则不要输出英文翻译。
            - 剧情模板只负责故事结构、人物关系、冲突和情绪弧线；只有用户明确要求分镜、镜号、景别或表格时，才输出分镜脚本。

            当用户要求生成、分析、改写或拆解创作内容时，优先使用以下结构：
            【理解你的需求】                      
            【知识库依据】
            【视频创作拆解】
            【优化后提示词】或【示例提示词：具体示例名】
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

    def _is_expression_voice_request(self, question: str) -> bool:
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

    def _build_model_identity_answer(self) -> str:
        rag_model = config.rag_model or "未配置"
        dashscope_model = config.dashscope_model or "未配置"
        if rag_model == dashscope_model:
            summary = f"我当前对话/RAG 使用的模型是 `{rag_model}`。"
        else:
            summary = f"我当前对话/RAG 使用的是 `{rag_model}`，DashScope 默认模型配置是 `{dashscope_model}`。"

        return (
            f"{summary}\n\n"
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
        has_pii = any(term in normalized for term in pii_terms)
        asks_to_disclose = any(action in normalized for action in disclosure_actions)
        targets_other_or_bulk = any(subject in normalized for subject in protected_subjects)
        asks_for_safe_guidance = any(term in normalized for term in safe_guidance_terms)

        if has_secret and asks_to_disclose:
            return "secret_disclosure"
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
        if any(word in q for word in ("动作设计师", "动作拆解", "最终动作提示词")):
            return "【示例提示词：动作过程细化】"

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
            "- 可复制提示词区块必须自包含，并包含“正向提示词”和“负面提示词”。\n"
        ]
        if is_character_prompt:
            skin_rule = (
                "如用户明确要求禁塑料感、真人感或写实皮肤，可在正向提示词末尾加入简短真实皮肤词；"
                if needs_real_skin
                else "不得默认加入活人感、毛孔、皮肤微纹理、痘印、油光等皮肤细节板块；"
            )
            extra_contracts.append(
                "- 人物角色/三视图：最终提示词服务于单张人物三视图卡；未指定画风默认真人写实风格，指定画风则遵从用户。"
                "画面要求：纯白背景，左 1/3 超大正面面部特写，右 2/3 正/侧/后完整全身，标准自然站姿，无姿态、无表情、无道具、无裁切。"
                "给出静态人设记忆点与视觉锚点；不得输出【服装道具】【活人感细节】【声音语气】【角色视频使用建议】等旧视频模板板块。"
                "负面提示词排除文字水印、缺脚裁切、视图不完整/错位、脸/发型/服装不一致、任何道具武器、背景场景、夸张动作表情。"
                f"{skin_rule}\n"
            )
        if is_expression_prompt:
            extra_contracts.append(
                "- 表情语气：只聚焦脸部与声音表达，如眼神、眉毛、眼睑、嘴角、唇部、面部肌肉、音量、语速、停顿、气息和尾音；"
                "不得默认写全身动作、走位、手势、道具或动作链。\n"
            )
        if is_scene_prompt:
            extra_contracts.append(
                "- 场景画面：可以输出色调方案用于统一主色、辅助色、阴影和光源色温；除非用户明确要求，不得让画面出现色卡块或文字说明。\n"
            )

        prompt = (
            f"用户原始问题：\n{question}\n\n"
            f"【服务端强制知识库检索结果】\n{grounding_context}\n\n"
            f"【本次提示词区块强制标题】\n{prompt_section_title}\n\n"
            "【强制回答约束】\n"
            "1. 优先依据检索结果；命中时【知识库依据】只列实际使用的 1-2 条，不写文件路径或 source；未命中则说明无直接依据并标为创作建议。\n"
            "2. 不得编造知识库不存在的结论、模型能力、案例、参数或规则。\n"
            f"3. 最终提示词只输出一份，标题必须逐字使用：{prompt_section_title}；不要再输出同义重复提示词区块。\n"
            "4. 默认只输出中文；用户明确要求英文/中英双语时除外。\n"
            "5. 剧情类问题不要默认拆分镜；只有用户明确要求分镜/镜头表格时才输出分镜脚本。\n"
            "6. 提示词用自然语言多行分段，不使用“人物/场景/情绪/动作过程/镜头/负面约束”这类斜杠字段模板。\n"
            "7. 回答末尾包含【回答自检】，检查完整性、依据真实性和仍需补充的信息。\n"
            f"{''.join(extra_contracts)}"
        )
        self._store_grounded_prompt_cache(cache_key, prompt, docs_signature)
        return prompt, False

    async def query(
        self,
        question: str,
        session_id: str,
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
            request_started_at = perf_counter()
            sensitive_category = self._classify_sensitive_info_request(question)
            if sensitive_category:
                logger.warning(
                    f"[会话 {session_id}] 拦截敏感信息请求: category={sensitive_category}, length={len(question)}"
                )
                return self._build_sensitive_refusal(sensitive_category)

            if self._is_model_identity_request(question):
                logger.info(f"[会话 {session_id}] 命中模型配置查询，直接返回当前模型配置")
                return self._build_model_identity_answer()

            init_started_at = perf_counter()
            await self._initialize_agent()
            init_elapsed_ms = (perf_counter() - init_started_at) * 1000

            logger.info(f"[会话 {session_id}] RAG Agent 收到查询（非流式）: {question}")

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
            result = await self.agent.ainvoke(
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
                logger.info(f"[会话 {session_id}] 命中模型配置查询（流式），直接返回当前模型配置")
                answer = self._build_model_identity_answer()
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
            await self._initialize_agent()
            init_elapsed_ms = (perf_counter() - init_started_at) * 1000

            logger.info(f"[会话 {session_id}] RAG Agent 收到查询（流式）: {question}")

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

            async for token, metadata in self.agent.astream(
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
            # MCP 客户端由全局管理器统一管理，无需手动清理
            logger.info("RAG Agent 服务资源已清理")
        except Exception as e:
            logger.error(f"清理资源失败: {e}")


# 全局单例 - 启用流式输出
rag_agent_service = RagAgentService(streaming=True)
