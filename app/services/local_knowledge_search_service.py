"""Local fallback search for bundled knowledge-base markdown files."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from langchain_core.documents import Document
from loguru import logger

from app.config import config


class LocalKnowledgeSearchService:
    """Small lexical fallback used when the vector store has no hits."""

    DOMAIN_TERMS = (
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
        "互动",
        "对视",
        "镜头跟随",
        "风格",
        "美学",
        "画风",
        "视觉风格",
        "风格关键词",
        "二次元",
        "动漫",
        "动画",
        "漫剧",
        "赛博朋克",
        "水墨",
        "角色",
        "人物设定",
        "角色设定",
        "设定卡",
        "一致性",
        "三视图",
        "正视图",
        "侧视图",
        "后视图",
        "场景",
        "场景提示词",
        "图片分析",
        "图片生成",
        "光影",
        "色卡",
        "构图",
        "表情",
        "语气",
        "台词",
        "眼神",
        "微表情",
        "剧本",
        "脚本",
        "分镜",
        "剧情",
        "故事大纲",
    )

    def __init__(self) -> None:
        self._chunk_cache: dict[str, tuple[float, int, list[Document]]] = {}

    def search(
        self,
        query: str,
        *,
        target_files: list[str] | None = None,
        k: int = 5,
    ) -> list[Document]:
        knowledge_base_path = Path(config.knowledge_base_path)
        if not knowledge_base_path.exists():
            logger.warning(f"本地知识库目录不存在: {knowledge_base_path}")
            return []

        files = self._resolve_files(knowledge_base_path, target_files)
        if not files:
            return []

        terms = self._extract_terms(query)
        if not terms:
            return []

        target_file_set = set(target_files or [])
        scored_docs: list[tuple[float, Document]] = []
        for file_path in files:
            for doc in self._load_markdown_chunks(file_path):
                score = self._score_doc(doc, terms)
                if file_path.name in target_file_set:
                    score += 3
                if score > 0:
                    scored_docs.append((score, doc))

        scored_docs.sort(key=lambda item: item[0], reverse=True)
        docs = [doc for _, doc in scored_docs[:k]]
        logger.info(
            "Local knowledge fallback search completed: "
            f"files={len(files)}, target_files={target_files or []}, count={len(docs)}"
        )
        return docs

    def _resolve_files(self, knowledge_base_path: Path, target_files: list[str] | None) -> list[Path]:
        if target_files:
            files = [
                knowledge_base_path / file_name
                for file_name in target_files
                if file_name.endswith(".md") and (knowledge_base_path / file_name).is_file()
            ]
            if files:
                return files

        return [
            file_path
            for file_path in sorted(knowledge_base_path.glob("*.md"))
            if file_path.is_file()
        ]

    def _load_markdown_chunks(self, file_path: Path) -> list[Document]:
        stat = file_path.stat()
        cache_key = str(file_path.resolve())
        cached = self._chunk_cache.get(cache_key)
        if cached and cached[0] == stat.st_mtime and cached[1] == stat.st_size:
            return list(cached[2])

        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning(f"读取本地知识库文件失败: {file_path}, error={exc}")
            return []

        docs = self._split_markdown(content, file_path)
        self._chunk_cache[cache_key] = (stat.st_mtime, stat.st_size, docs)
        return list(docs)

    def _split_markdown(self, content: str, file_path: Path) -> list[Document]:
        h1_match = re.search(r"(?m)^#\s+(.+)$", content)
        h1 = h1_match.group(1).strip() if h1_match else file_path.stem
        h2_matches = list(re.finditer(r"(?m)^##\s+(.+)$", content))

        sections: list[tuple[str, str]] = []
        if h2_matches:
            prelude = content[: h2_matches[0].start()].strip()
            if len(prelude) >= 120:
                sections.append((h1, prelude))
            for index, match in enumerate(h2_matches):
                start = match.start()
                end = h2_matches[index + 1].start() if index + 1 < len(h2_matches) else len(content)
                sections.append((match.group(1).strip(), content[start:end].strip()))
        elif content.strip():
            sections.append((h1, content.strip()))

        docs: list[Document] = []
        for index, (h2, section) in enumerate(sections, 1):
            if not section:
                continue
            docs.append(
                Document(
                    page_content=section,
                    metadata={
                        "h1": h1,
                        "h2": h2,
                        "chunk_title": h2,
                        "chunk_id": f"local_{index:03d}",
                        "content_type": "local_fallback",
                        "_source": file_path.resolve().as_posix(),
                        "_extension": ".md",
                        "_file_name": file_path.name,
                    },
                )
            )
        return docs

    def _extract_terms(self, query: str) -> set[str]:
        terms = {term for term in self.DOMAIN_TERMS if term in query}
        terms.update(
            token
            for token in re.findall(r"[A-Za-z0-9_+-]{2,}", query)
            if len(token) >= 2
        )

        for segment in re.findall(r"[\u4e00-\u9fff]{2,}", query):
            if len(segment) <= 12:
                terms.add(segment)
            terms.update(self._ngrams(segment, 2))
            terms.update(self._ngrams(segment, 3))
            terms.update(self._ngrams(segment, 4))

        return {term for term in terms if len(term.strip()) >= 2}

    def _ngrams(self, text: str, size: int) -> Iterable[str]:
        if len(text) < size:
            return ()
        return (text[index : index + size] for index in range(len(text) - size + 1))

    def _score_doc(self, doc: Document, terms: set[str]) -> float:
        metadata = doc.metadata or {}
        title = " ".join(
            str(metadata.get(key) or "")
            for key in ("h1", "h2", "h3", "chunk_title", "_file_name")
        )
        content = doc.page_content or ""

        score = 0.0
        for term in terms:
            if term in title:
                score += 4
            count = content.count(term)
            if count:
                score += min(count, 8)
        return score


local_knowledge_search_service = LocalKnowledgeSearchService()
