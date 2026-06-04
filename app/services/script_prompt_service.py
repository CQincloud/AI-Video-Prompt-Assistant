"""Script-based prompt reference service.

This module implements the MVP flow for turning a pasted screenplay into
referenced prompt context. It intentionally keeps script storage out of the
first version: the caller sends script text for parsing, then sends the parsed
structure back when retrieving references for the normal chat generator.
"""

from __future__ import annotations

import importlib
import io
import re
import zipfile
import zlib
from dataclasses import dataclass
from hashlib import sha1
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


class ScriptPromptError(RuntimeError):
    """User-facing script prompt error."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class ScriptPromptRequest:
    generation_type: str
    target: str
    platform: str
    user_requirement: str
    include_english: bool = False


class ScriptPromptService:
    """Parse scripts and retrieve references for existing prompt templates."""

    GENERATION_TYPES = {
        "character": "人物提示词",
        "scene": "场景提示词",
    }
    PLATFORMS = {
        "general": "通用",
        "midjourney": "Midjourney",
        "stable_diffusion": "Stable Diffusion",
        "jimeng": "即梦",
        "kling": "可灵",
        "runway": "Runway",
        "pika": "Pika",
    }
    COLD_OPEN_SCENE_TERMS = (
        "冷开场",
        "开场钩子",
        "预告钩子",
        "片头钩子",
        "高能开场",
        "先导钩子",
        "前情钩子",
    )
    TIME_WORDS = {
        "日",
        "夜",
        "早",
        "晨",
        "午",
        "晚",
        "晴",
        "阴",
        "清晨",
        "早晨",
        "上午",
        "中午",
        "下午",
        "黄昏",
        "傍晚",
        "深夜",
        "白日",
        "白天",
        "夜晚",
        "雨日",
        "雨夜",
        "雨天",
        "下雨",
        "晴天",
        "阴天",
        "小雨",
        "大雨",
        "暴雨",
        "雪日",
        "雪夜",
        "雪天",
        "下雪",
        "黎明",
        "拂晓",
        "凌晨",
        "午前",
        "午后",
        "日间",
    }
    EMOTION_WORDS = [
        "害怕",
        "坚定",
        "紧张",
        "沮丧",
        "温柔",
        "震惊",
        "冷漠",
        "不屑",
        "激动",
        "难以置信",
        "凶狠",
        "平静",
        "自信",
        "痛苦",
        "欣慰",
        "孤傲",
        "压迫",
    ]
    VISUAL_WORDS = [
        "阳光",
        "青石",
        "演武场",
        "树林",
        "山洞",
        "小镇",
        "广场",
        "白衣",
        "长剑",
        "剑光",
        "残影",
        "夕阳",
        "晚霞",
        "山顶",
        "血",
        "内力",
        "音波",
        "尘土",
        "宗门",
    ]
    ACTION_WORDS = [
        "出拳",
        "摔",
        "扶起",
        "抓住",
        "拍",
        "打通",
        "打出",
        "练起",
        "飞身",
        "点向",
        "出鞘",
        "倒飞",
        "踢向",
        "后退",
        "刺向",
        "挥舞",
        "闭上眼睛",
        "睁开眼睛",
        "掉在地上",
    ]
    GENRE_WORDS = [
        "民国",
        "悬疑",
        "推理",
        "复仇",
        "双女主",
        "武侠",
        "仙侠",
        "玄幻",
        "都市",
        "校园",
        "现实",
        "年代",
        "谍战",
        "权谋",
        "宫廷",
        "短剧",
        "漫剧",
    ]
    WORLDVIEW_WORDS = [
        "架空",
        "宗门",
        "江湖",
        "省衙",
        "县衙",
        "山门",
        "门派",
        "仙门",
        "王朝",
        "朝廷",
        "民国",
        "小镇",
        "山地",
        "边城",
    ]
    REGION_WORDS = [
        "长安",
        "江南",
        "武陵",
        "苗疆",
        "西域",
        "塞北",
        "岭南",
        "中原",
        "南洋",
        "上海",
        "北平",
        "山城",
        "边陲",
        "山寨",
        "古镇",
        "小镇",
    ]
    OCCUPATION_WORDS = [
        "差头",
        "捕快",
        "差役",
        "侦探",
        "警察",
        "军官",
        "士兵",
        "剑客",
        "弟子",
        "掌门",
        "长老",
        "大夫",
        "郎中",
        "商人",
        "掌柜",
        "学生",
        "记者",
        "戏子",
        "歌女",
        "新娘",
        "夫人",
        "少爷",
        "小姐",
        "县令",
        "知府",
    ]
    PROP_WORDS = [
        "长剑",
        "佩刀",
        "腰牌",
        "官靴",
        "卷宗",
        "画像",
        "油灯",
        "铜灯",
        "火塘",
        "傩面",
        "面具",
        "剪报",
        "雨伞",
        "手枪",
        "旗帜",
        "令牌",
        "秘籍",
        "酒楼",
        "山门",
        "观星楼",
        "女牢",
    ]
    VISUAL_TONE_WORDS = [
        "雨夜",
        "冷色",
        "低饱和",
        "写实",
        "电影感",
        "压抑",
        "阴冷",
        "复仇",
        "克制",
        "血色",
        "雾气",
        "烛光",
        "火光",
        "月光",
        "夕阳",
        "逆光",
    ]
    TEXT_UPLOAD_EXTENSIONS = {"txt", "md", "markdown"}
    DOCUMENT_UPLOAD_EXTENSIONS = {"docx", "pdf"}
    SUPPORTED_UPLOAD_EXTENSIONS = TEXT_UPLOAD_EXTENSIONS | DOCUMENT_UPLOAD_EXTENSIONS

    def extract_script_text_from_file(self, filename: str, content: bytes) -> dict[str, Any]:
        safe_filename = Path(filename or "").name
        extension = Path(safe_filename).suffix.lower().lstrip(".")
        if extension not in self.SUPPORTED_UPLOAD_EXTENSIONS:
            raise ScriptPromptError("剧本文档仅支持 TXT、Markdown、Word(.docx) 或 PDF")
        if not content:
            raise ScriptPromptError("上传的剧本文档为空，请重新选择文件")

        if extension in self.TEXT_UPLOAD_EXTENSIONS:
            text = self._decode_text_upload(content)
        elif extension == "docx":
            text = self._extract_docx_text(content)
        else:
            text = self._extract_pdf_text(content)

        clean_text = self._cleanup_extracted_text(text)
        if len(clean_text) < 20:
            raise ScriptPromptError("文档中没有提取到足够的剧本文本，请检查文件内容")
        if len(clean_text) > 120_000:
            raise ScriptPromptError("剧本文档内容过长，第一版请控制在 12 万字以内")

        title = Path(safe_filename).stem.strip() or self._extract_title(clean_text, None)
        return {
            "filename": safe_filename,
            "title": title[:80],
            "extension": extension,
            "text": clean_text,
        }

    def parse_script(self, script_text: str, title: str | None = None) -> dict[str, Any]:
        clean_text = self._normalize_text(script_text)
        if len(clean_text) < 20:
            raise ScriptPromptError("剧本内容太短，请粘贴完整剧本后再解析")
        if len(clean_text) > 120_000:
            raise ScriptPromptError("剧本内容过长，第一版请控制在 12 万字以内")

        script_title = self._extract_title(clean_text, title)
        characters = self._extract_characters(clean_text)
        scenes = self._extract_scenes(clean_text, characters)
        chunks = self._build_chunks(script_title, characters, scenes)
        visual_context = self._extract_visual_context(clean_text, characters, scenes, chunks)

        character_names = {character["name"] for character in characters}
        scene_summaries = []
        for scene in scenes:
            scene_chunks = [chunk for chunk in chunks if chunk.get("scene_id") == scene["scene_id"]]
            scene_summaries.append(
                {
                    **scene,
                    "chunk_count": len(scene_chunks),
                    "characters": sorted(
                        {
                            name
                            for chunk in scene_chunks
                            for name in chunk.get("characters", [])
                            if name in character_names
                        }
                    ),
                }
            )

        return {
            "script_id": self._slugify(script_title) or "script_current",
            "title": script_title,
            "characters": characters,
            "scenes": scene_summaries,
            "chunks": chunks,
            "visual_context": visual_context,
            "stats": {
                "character_count": len(characters),
                "scene_count": len(scenes),
                "chunk_count": len(chunks),
                "action_count": sum(1 for chunk in chunks if "action" in chunk["chunk_type"]),
                "dialogue_count": sum(1 for chunk in chunks if chunk["chunk_type"] == "dialogue"),
            },
        }

    def validate_reference_request(
        self,
        parsed_script: dict[str, Any],
        request: ScriptPromptRequest,
    ) -> None:
        if not parsed_script or not parsed_script.get("chunks"):
            raise ScriptPromptError("请先解析剧本，再生成提示词")
        if request.generation_type not in self.GENERATION_TYPES:
            raise ScriptPromptError("当前生成类型没有对应的系统提示词模板")
        if len(request.user_requirement or "") > 3000:
            raise ScriptPromptError("补充需求过长，请精简到 3000 字以内")
        if request.generation_type == "scene" and self._is_cold_open_scene_text(request.target):
            raise ScriptPromptError("冷开场不作为单独场景生成，请选择具体地点或具体场景片段")

    def retrieve_references(
        self,
        parsed_script: dict[str, Any],
        request: ScriptPromptRequest,
        *,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        chunks = list(parsed_script.get("chunks") or [])
        if request.generation_type == "scene":
            chunks = [
                chunk
                for chunk in chunks
                if not self._is_cold_open_scene_text(
                    " ".join(
                        str(chunk.get(key) or "")
                        for key in ("source", "scene", "location")
                    )
                )
            ]
        if not chunks:
            return []

        scored: list[tuple[int, int, dict[str, Any]]] = []
        target = (request.target or "").strip()
        requirement = request.user_requirement or ""
        query_terms = self._extract_query_terms(f"{target} {requirement}")
        for index, chunk in enumerate(chunks):
            score = self._score_chunk(chunk, request, query_terms)
            if score > 0:
                scored.append((score, index, chunk))

        if not scored:
            scored = [(1, index, chunk) for index, chunk in enumerate(chunks[:limit])]

        scored.sort(key=lambda item: (-item[0], item[1]))
        selected: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for _score, _index, chunk in scored:
            chunk_id = str(chunk.get("chunk_id") or "")
            if not chunk_id or chunk_id in seen_ids:
                continue
            seen_ids.add(chunk_id)
            selected.append(self._public_reference(chunk, request))
            if len(selected) >= limit:
                break
        return selected

    def _extract_visual_context(
        self,
        script_text: str,
        characters: list[dict[str, Any]],
        scenes: list[dict[str, Any]],
        chunks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        character_text = "\n".join(
            f"{character.get('name', '')} {character.get('description', '')}"
            for character in characters
        )
        scene_text = "\n".join(
            " ".join(
                str(scene.get(key) or "")
                for key in ("scene_number", "location", "time", "heading")
            )
            for scene in scenes
        )
        chunk_text = "\n".join(str(chunk.get("content") or "") for chunk in chunks[:240])
        combined = "\n".join([script_text[:24000], character_text, scene_text, chunk_text])

        era_hints = self._extract_era_hints(combined)
        genre_hints = self._collect_keyword_hits(combined, self.GENRE_WORDS)
        worldview_hints = self._collect_keyword_hits(combined, self.WORLDVIEW_WORDS)
        region_hints = self._collect_keyword_hits(combined, self.REGION_WORDS)
        occupation_hints = self._collect_keyword_hits(combined, self.OCCUPATION_WORDS)
        prop_hints = self._collect_keyword_hits(combined, self.PROP_WORDS)
        tone_hints = self._collect_keyword_hits(combined, self.VISUAL_TONE_WORDS)

        evidence_terms: list[str] = []
        for values in (
            era_hints,
            genre_hints,
            worldview_hints,
            region_hints,
            occupation_hints,
            prop_hints,
            tone_hints,
        ):
            for value in values:
                term = value.split("（", 1)[0].strip()
                if term and term not in evidence_terms:
                    evidence_terms.append(term)

        return {
            "strategy": "V1 只做剧本信息提取、视觉方向约束和防跑偏负面提示词；不做联网考据。",
            "era_hints": era_hints[:8],
            "genre_hints": genre_hints[:10],
            "worldview_hints": worldview_hints[:10],
            "region_hints": region_hints[:10],
            "occupation_hints": occupation_hints[:12],
            "prop_hints": prop_hints[:12],
            "tone_hints": tone_hints[:10],
            "evidence_quotes": self._find_evidence_quotes(script_text, evidence_terms),
        }

    def _extract_era_hints(self, text: str) -> list[str]:
        hints: list[str] = []

        def add(value: str) -> None:
            clean = re.sub(r"\s+", "", value).strip()
            if clean and clean not in hints:
                hints.append(clean)

        for match in re.finditer(r"民国\s*([一二三四五六七八九十百〇零两\d]{1,4})\s*年", text):
            raw = match.group(0)
            year_number = self._chinese_year_number_to_int(match.group(1))
            if year_number:
                gregorian_year = 1911 + year_number
                decade = (gregorian_year // 10) * 10
                add(f"{raw}（约{gregorian_year}年，{decade}年代）")
            else:
                add(raw)

        for match in re.finditer(r"(?:公元)?\s*\d{3,4}\s*年", text):
            add(match.group(0))
        for match in re.finditer(r"\d{2,4}\s*年代", text):
            add(match.group(0))

        era_terms = [
            "先秦",
            "秦代",
            "汉代",
            "魏晋",
            "南北朝",
            "隋唐",
            "唐代",
            "宋代",
            "元代",
            "明代",
            "清代",
            "民国",
            "现代",
            "当代",
            "近未来",
            "未来",
            "古代",
            "架空古代",
            "上古",
            "末世",
        ]
        for term in era_terms:
            if term in text:
                add(term)
        return hints[:12]

    def _chinese_year_number_to_int(self, value: str) -> int | None:
        clean = re.sub(r"\s+", "", value or "")
        if not clean:
            return None
        if clean.isdigit():
            return int(clean)

        digits = {
            "零": 0,
            "〇": 0,
            "一": 1,
            "二": 2,
            "两": 2,
            "三": 3,
            "四": 4,
            "五": 5,
            "六": 6,
            "七": 7,
            "八": 8,
            "九": 9,
        }
        if all(char in digits for char in clean):
            return int("".join(str(digits[char]) for char in clean))

        if "百" in clean:
            left, _, right = clean.partition("百")
            total = (digits.get(left, 1) if left else 1) * 100
            if right:
                tail = self._chinese_year_number_to_int(right)
                if tail is not None:
                    total += tail
            return total

        if "十" in clean:
            left, _, right = clean.partition("十")
            total = (digits.get(left, 1) if left else 1) * 10
            if right:
                total += digits.get(right, 0)
            return total
        return None

    def _collect_keyword_hits(self, text: str, candidates: list[str], *, limit: int = 16) -> list[str]:
        hits: list[str] = []
        for candidate in candidates:
            if candidate in text and candidate not in hits:
                hits.append(candidate)
            if len(hits) >= limit:
                break
        return hits

    def _find_evidence_quotes(self, script_text: str, terms: list[str], *, limit: int = 8) -> list[dict[str, str]]:
        quotes: list[dict[str, str]] = []
        seen_quotes: set[str] = set()
        lines = [self._clean_inline_markdown(line.strip()) for line in script_text.splitlines()]
        for term in terms:
            if not term:
                continue
            for line in lines:
                if term not in line:
                    continue
                clean = re.sub(r"\s+", " ", line).strip()
                if not clean or clean in seen_quotes:
                    continue
                seen_quotes.add(clean)
                quotes.append({"term": term, "quote": clean[:180]})
                break
            if len(quotes) >= limit:
                break
        return quotes

    def _normalize_text(self, text: str) -> str:
        return (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()

    def _cleanup_extracted_text(self, text: str) -> str:
        text = self._normalize_text(text)
        text = re.sub(r"[ \t\f\v]+", " ", text)
        text = re.sub(r"\n[ \t]+", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _decode_text_upload(self, content: bytes) -> str:
        for encoding in ("utf-8-sig", "utf-8", "gb18030", "big5"):
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        return content.decode("utf-8", errors="ignore")

    def _extract_docx_text(self, content: bytes) -> str:
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as docx:
                names = set(docx.namelist())
                if "word/document.xml" not in names:
                    raise ScriptPromptError("Word 文档格式不正确，请上传 .docx 文件")

                xml_names = ["word/document.xml"]
                xml_names.extend(
                    sorted(
                        name
                        for name in names
                        if re.match(r"word/(?:header|footer)\d+\.xml$", name)
                    )
                )
                paragraphs: list[str] = []
                for xml_name in xml_names:
                    paragraphs.extend(self._docx_xml_to_paragraphs(docx.read(xml_name)))
        except ScriptPromptError:
            raise
        except zipfile.BadZipFile as exc:
            raise ScriptPromptError("Word 文档格式不正确，请上传 .docx 文件") from exc
        except ET.ParseError as exc:
            raise ScriptPromptError("Word 文档内容解析失败，请检查文件是否损坏") from exc

        text = "\n".join(paragraphs)
        if not text.strip():
            raise ScriptPromptError("Word 文档中没有提取到可用文本")
        return text

    def _docx_xml_to_paragraphs(self, xml_bytes: bytes) -> list[str]:
        root = ET.fromstring(xml_bytes)
        paragraphs: list[str] = []
        for paragraph in root.iter():
            if not paragraph.tag.endswith("}p"):
                continue
            chunks: list[str] = []
            for node in paragraph.iter():
                tag = node.tag.rsplit("}", 1)[-1]
                if tag == "t" and node.text:
                    chunks.append(node.text)
                elif tag == "tab":
                    chunks.append("\t")
                elif tag in {"br", "cr"}:
                    chunks.append("\n")
            text = "".join(chunks).strip()
            if text:
                paragraphs.append(text)
        return paragraphs

    def _extract_pdf_text(self, content: bytes) -> str:
        errors: list[str] = []
        for module_name in ("pypdf", "PyPDF2"):
            try:
                module = importlib.import_module(module_name)
                reader = module.PdfReader(io.BytesIO(content))
                page_text = [page.extract_text() or "" for page in reader.pages]
                text = "\n".join(page_text).strip()
                if text:
                    return text
            except Exception as exc:  # pragma: no cover - depends on optional PDF libraries
                errors.append(f"{module_name}: {exc}")

        try:
            pdfplumber = importlib.import_module("pdfplumber")
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                page_text = [page.extract_text() or "" for page in pdf.pages]
            text = "\n".join(page_text).strip()
            if text:
                return text
        except Exception as exc:  # pragma: no cover - depends on optional PDF libraries
            errors.append(f"pdfplumber: {exc}")

        text = self._extract_pdf_text_basic(content)
        if text:
            return text

        detail = "；".join(errors[:2])
        suffix = f"（{detail}）" if detail else ""
        raise ScriptPromptError(f"PDF 文档中没有提取到可用文本；如果是扫描件，请先 OCR 后再上传{suffix}")

    def _extract_pdf_text_basic(self, content: bytes) -> str:
        stream_blocks = self._extract_pdf_stream_blocks(content)
        source = b"\n".join(stream_blocks) if stream_blocks else content
        text = self._extract_pdf_text_operators(source)
        return self._cleanup_extracted_text(text)

    def _extract_pdf_stream_blocks(self, content: bytes) -> list[bytes]:
        blocks: list[bytes] = []
        pattern = re.compile(rb"(?s)(<<.*?>>)\s*stream\r?\n(.*?)\r?\nendstream")
        for match in pattern.finditer(content):
            header = match.group(1)
            body = match.group(2).strip(b"\r\n")
            if b"/FlateDecode" in header:
                try:
                    body = zlib.decompress(body)
                except zlib.error:
                    continue
            blocks.append(body)
        return blocks

    def _extract_pdf_text_operators(self, source: bytes) -> str:
        parts: list[str] = []
        for match in re.finditer(rb"(\((?:\\.|[^\\()])*\))\s*(?:Tj|'|\")", source, flags=re.S):
            parts.append(self._decode_pdf_literal(match.group(1)))
        for match in re.finditer(rb"\[(.*?)\]\s*TJ", source, flags=re.S):
            for literal in re.findall(rb"\((?:\\.|[^\\()])*\)", match.group(1), flags=re.S):
                parts.append(self._decode_pdf_literal(literal))
            for hex_text in re.findall(rb"<([0-9A-Fa-f\s]+)>", match.group(1)):
                parts.append(self._decode_pdf_hex(hex_text))
        for match in re.finditer(rb"<([0-9A-Fa-f\s]+)>\s*Tj", source, flags=re.S):
            parts.append(self._decode_pdf_hex(match.group(1)))

        if not parts:
            for literal in re.findall(rb"\((?:\\.|[^\\()]){4,}\)", source, flags=re.S):
                parts.append(self._decode_pdf_literal(literal))
        return "\n".join(part for part in parts if part.strip())

    def _decode_pdf_literal(self, literal: bytes) -> str:
        if literal.startswith(b"(") and literal.endswith(b")"):
            literal = literal[1:-1]
        output = bytearray()
        index = 0
        while index < len(literal):
            char = literal[index]
            if char != 0x5C:
                output.append(char)
                index += 1
                continue

            index += 1
            if index >= len(literal):
                break
            escaped = literal[index]
            if escaped in b"nrtbf":
                output.extend(
                    {
                        ord("n"): b"\n",
                        ord("r"): b"\r",
                        ord("t"): b"\t",
                        ord("b"): b"\b",
                        ord("f"): b"\f",
                    }[escaped]
                )
                index += 1
            elif escaped in b"()\\":
                output.append(escaped)
                index += 1
            elif 48 <= escaped <= 55:
                digits = bytes([escaped])
                index += 1
                while index < len(literal) and len(digits) < 3 and 48 <= literal[index] <= 55:
                    digits += bytes([literal[index]])
                    index += 1
                output.append(int(digits, 8))
            else:
                output.append(escaped)
                index += 1
        return self._decode_pdf_bytes(bytes(output))

    def _decode_pdf_hex(self, hex_text: bytes) -> str:
        clean = re.sub(rb"\s+", b"", hex_text)
        if len(clean) % 2 == 1:
            clean += b"0"
        try:
            return self._decode_pdf_bytes(bytes.fromhex(clean.decode("ascii")))
        except ValueError:
            return ""

    def _decode_pdf_bytes(self, data: bytes) -> str:
        if data.startswith(b"\xfe\xff"):
            return data[2:].decode("utf-16-be", errors="ignore")
        if data.startswith(b"\xff\xfe"):
            return data[2:].decode("utf-16-le", errors="ignore")
        if b"\x00" in data[:20]:
            for encoding in ("utf-16-be", "utf-16-le"):
                try:
                    return data.decode(encoding)
                except UnicodeDecodeError:
                    continue
        for encoding in ("utf-8", "gb18030", "latin-1"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="ignore")

    def _extract_title(self, script_text: str, explicit_title: str | None) -> str:
        if explicit_title and explicit_title.strip():
            return explicit_title.strip()[:80]
        for line in script_text.splitlines():
            match = re.match(r"^\s*#\s+(.+?)\s*$", line)
            if match:
                return match.group(1).strip()[:80]
        return "未命名剧本"

    def _extract_characters(self, script_text: str) -> list[dict[str, Any]]:
        lines = script_text.splitlines()
        in_character_section = False
        characters: list[dict[str, Any]] = []
        seen: set[str] = set()
        current_profile: dict[str, Any] | None = None
        supporting_table = False

        for line in lines:
            clean = line.strip()
            if self._is_character_section_heading(clean):
                in_character_section = True
                current_profile = None
                supporting_table = False
                continue
            if in_character_section and self._is_next_major_section_heading(clean):
                break
            if not in_character_section:
                continue
            if not clean or self._is_rule_line(clean):
                continue

            match = re.match(
                r"^\s*[-*]\s*(?:\*\*)?(?P<name>[^*：:]+?)(?:\*\*)?\s*[：:]\s*(?P<desc>.+)$",
                line,
            )
            if match:
                name = self._normalize_character_name(match.group("name"))
                description = self._clean_inline_markdown(match.group("desc").strip())
                current_profile = self._add_character(characters, seen, name, description)
                supporting_table = False
                continue

            table_cells = self._parse_table_row(clean)
            if table_cells:
                if self._is_table_separator(table_cells):
                    continue
                if current_profile and len(table_cells) >= 2 and not supporting_table:
                    key = self._clean_inline_markdown(table_cells[0])
                    value = self._clean_inline_markdown(table_cells[1])
                    if key and value and key not in {"项", "内容"}:
                        current_profile["description"] = self._append_profile_field(
                            current_profile.get("description") or "",
                            key,
                            value,
                        )
                    continue
                if len(table_cells) >= 2 and self._looks_like_supporting_character_row(table_cells):
                    name = self._normalize_character_name(table_cells[0])
                    description = self._clean_inline_markdown(table_cells[1])
                    current_profile = self._add_character(characters, seen, name, description)
                    supporting_table = True
                    continue

            if clean in {"配角", "其他角色", "配角表"}:
                current_profile = None
                supporting_table = True
                continue

            profile_heading = self._parse_character_profile_heading(clean)
            if profile_heading:
                name, role = profile_heading
                current_profile = self._add_character(characters, seen, name, role)
                supporting_table = False
                continue
            if current_profile and not supporting_table:
                current_profile["description"] = self._append_profile_text(
                    current_profile.get("description") or "",
                    self._clean_inline_markdown(clean),
                )
        if not characters:
            characters = self._extract_characters_from_dialogue(script_text)
        return characters

    def _is_character_section_heading(self, line: str) -> bool:
        clean = line.lstrip("#").strip()
        return bool(
            re.match(
                r"^(?:[一二三四五六七八九十百\d]+[、.．]\s*)?"
                r"(?:人物表|人物小传|人物设定|人物介绍|角色表|角色小传|角色设定|角色介绍|主要人物)",
                clean,
            )
        )

    def _is_next_major_section_heading(self, line: str) -> bool:
        clean = line.lstrip("#").strip()
        if self._is_character_section_heading(clean):
            return False
        return bool(re.match(r"^[一二三四五六七八九十百\d]+[、.．]\s*\S+", clean))

    def _parse_character_profile_heading(self, line: str) -> tuple[str, str] | None:
        if line.startswith("|") or len(line) > 60:
            return None
        match = re.match(
            r"^(?P<name>[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z·\s　]{0,12})"
            r"(?:[（(](?P<role>[^)）]{1,40})[)）])\s*$",
            line,
        )
        if not match:
            return None
        name = self._normalize_character_name(match.group("name"))
        role = self._clean_inline_markdown(match.group("role") or "")
        if not name or name in {"配角", "角色", "人物", "内容"}:
            return None
        return name, role

    def _parse_table_row(self, line: str) -> list[str] | None:
        if not line.startswith("|") or "|" not in line[1:]:
            return None
        cells = [self._clean_inline_markdown(cell.strip()) for cell in line.strip("|").split("|")]
        return [cell for cell in cells]

    def _is_table_separator(self, cells: list[str]) -> bool:
        return all(re.fullmatch(r":?-{2,}:?", cell or "") for cell in cells)

    def _looks_like_supporting_character_row(self, cells: list[str]) -> bool:
        if len(cells) < 2:
            return False
        first = self._normalize_character_name(cells[0])
        second = cells[1].strip()
        if first in {"角色", "人物", "项", "内容"}:
            return False
        return bool(first and second and len(first) <= 8)

    def _add_character(
        self,
        characters: list[dict[str, Any]],
        seen: set[str],
        name: str,
        description: str,
    ) -> dict[str, Any] | None:
        name = self._normalize_character_name(name)
        description = self._clean_inline_markdown(description)
        if not name:
            return None
        if name in seen:
            for character in characters:
                if character["name"] == name and description:
                    character["description"] = self._append_profile_text(character["description"], description)
                    character["gender"] = self._extract_gender(character["description"])
                    character["age"] = self._extract_age(character["description"])
                    return character
            return None
        seen.add(name)
        character = {
            "name": name,
            "description": description,
            "gender": self._extract_gender(description),
            "age": self._extract_age(description),
        }
        characters.append(character)
        return character

    def _append_profile_field(self, description: str, key: str, value: str) -> str:
        field = f"{key}：{value}"
        return self._append_profile_text(description, field)

    def _append_profile_text(self, description: str, text: str) -> str:
        text = text.strip()
        if not text:
            return description
        if not description:
            return text
        if text in description:
            return description
        return f"{description}；{text}"

    def _clean_inline_markdown(self, value: str) -> str:
        value = re.sub(r"</?br\s*/?>", " ", value or "", flags=re.I)
        value = re.sub(r"\*\*(.+?)\*\*", r"\1", value)
        value = re.sub(r"__([^_]+)__", r"\1", value)
        return value.strip()

    def _normalize_character_name(self, value: str) -> str:
        clean = self._clean_inline_markdown(value)
        clean = re.sub(r"^[\-*•]\s*", "", clean)
        clean = re.sub(r"(?<=[\u4e00-\u9fff])[\s　]+(?=[\u4e00-\u9fff])", "", clean)
        clean = clean.strip(" ：:，,、。")
        return clean

    def _mentions_character(self, content: str, name: str) -> bool:
        if not name:
            return False
        normalized_content = self._normalize_character_name(content)
        normalized_name = self._normalize_character_name(name)
        return normalized_name in normalized_content

    def _is_rule_line(self, line: str) -> bool:
        clean = line.strip()
        return bool(
            re.fullmatch(r"[-—─_=]{3,}", clean)
            or re.fullmatch(r"[┄┅┈┉━]+", clean)
            or re.fullmatch(r"\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)+\|?", clean)
        )

    def _extract_characters_from_dialogue(self, script_text: str) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        for line in script_text.splitlines():
            clean = line.strip()
            if not clean or len(clean) > 16:
                continue
            normalized = self._normalize_character_name(clean)
            if re.fullmatch(r"[\u4e00-\u9fffA-Za-z]{2,6}(?:[（(][^)）]{1,12}[)）])?", normalized):
                name = re.sub(r"[（(].*$", "", normalized)
                if name not in {"字幕", "黑底", "切片名", "副标识", "画外"}:
                    counts[name] = counts.get(name, 0) + 1
        characters: list[dict[str, Any]] = []
        seen: set[str] = set()
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:30]:
            if count >= 2:
                self._add_character(characters, seen, name, "根据台词格式自动识别的角色")
        return characters

    def _extract_scenes(
        self,
        script_text: str,
        characters: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        lines = script_text.splitlines()
        current_act = ""
        current_episode = ""
        current_scene: dict[str, Any] | None = None
        scenes: list[dict[str, Any]] = []

        for line in lines:
            clean = line.strip()
            act_match = re.match(r"^##\s+(第.+幕.+)$", clean)
            if act_match:
                current_act = act_match.group(1).strip()
                continue

            episode_match = self._parse_episode_heading(clean)
            if episode_match:
                current_episode = episode_match
                continue

            scene_match = self._parse_scene_heading(clean)
            if scene_match:
                if current_scene:
                    scenes.append(current_scene)
                scene_label = scene_match["scene_number"]
                rest = scene_match["rest"]
                location, time_label = self._split_scene_heading(rest)
                scene_id = f"scene_{len(scenes) + 1:03d}"
                act_label = current_episode or current_act
                current_scene = {
                    "scene_id": scene_id,
                    "act": act_label,
                    "scene_number": scene_label,
                    "location": location,
                    "time": time_label,
                    "heading": self._format_scene_source(act_label, scene_label, location),
                    "content_lines": [],
                }
                continue

            if current_scene is not None:
                current_scene["content_lines"].append(line)

        if current_scene:
            scenes.append(current_scene)

        if not scenes:
            scenes = self._fallback_single_scene(script_text)

        character_names = [character["name"] for character in characters]
        for scene in scenes:
            content = "\n".join(scene.get("content_lines") or [])
            scene["characters"] = [name for name in character_names if self._mentions_character(content, name)]
        return scenes

    def _parse_episode_heading(self, line: str) -> str | None:
        clean = line.lstrip("#").strip()
        match = re.match(r"^(第\s*\d+\s*集)\s*[·.．、:：-]\s*(.+?)\s*$", clean)
        if not match:
            return None
        title = match.group(2).strip()
        episode = re.sub(r"\s+", "", match.group(1))
        return f"{episode} · {title}" if title else episode

    def _parse_scene_heading(self, line: str) -> dict[str, str] | None:
        clean = line.lstrip("#").strip()
        markdown_match = re.match(r"^(场景[^\s]+)\s+(.+?)\s*$", clean)
        if markdown_match:
            return {
                "scene_number": markdown_match.group(1).strip(),
                "rest": markdown_match.group(2).strip(),
            }

        numbered_match = re.match(
            r"^(场\s*\d+(?:\.\d+)*)\s*[·.．、:：-]\s*(.+?)\s*$",
            clean,
        )
        if numbered_match:
            return {
                "scene_number": re.sub(r"\s+", "", numbered_match.group(1)),
                "rest": numbered_match.group(2).strip(),
            }

        special_terms = "|".join(
            re.escape(term)
            for term in (*self.COLD_OPEN_SCENE_TERMS, "序场", "片头", "尾声", "结尾", "彩蛋")
        )
        special_match = re.match(rf"^({special_terms})\s*[·.．、:：-]\s*(.+?)\s*$", clean)
        if special_match:
            return {
                "scene_number": special_match.group(1).strip(),
                "rest": special_match.group(2).strip(),
            }
        return None

    def _fallback_single_scene(self, script_text: str) -> list[dict[str, Any]]:
        return [
            {
                "scene_id": "scene_001",
                "act": "",
                "scene_number": "全文",
                "location": "未明确地点",
                "time": "",
                "heading": "全文",
                "content_lines": script_text.splitlines(),
                "characters": [],
            }
        ]

    def _build_chunks(
        self,
        script_title: str,
        characters: list[dict[str, Any]],
        scenes: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        chunks: list[dict[str, Any]] = []
        script_id = self._slugify(script_title) or "script_current"

        for index, character in enumerate(characters, start=1):
            chunks.append(
                {
                    "script_id": script_id,
                    "chunk_id": f"character_{index:03d}",
                    "scene_id": None,
                    "source": f"人物表 / {character['name']}",
                    "scene": "人物表",
                    "location": "",
                    "time": "",
                    "characters": [character["name"]],
                    "chunk_type": "character_description",
                    "content": f"{character['name']}：{character['description']}",
                    "emotion_tags": self._find_tags(character["description"], self.EMOTION_WORDS),
                    "visual_tags": self._find_tags(character["description"], self.VISUAL_WORDS),
                }
            )

        character_names = [character["name"] for character in characters]
        for scene_index, scene in enumerate(scenes, start=1):
            mode = "scene_description"
            paragraph_index = 0
            pending_speaker = ""
            for paragraph in self._iter_scene_paragraphs(scene.get("content_lines") or []):
                if self._is_action_marker(paragraph):
                    mode = "action"
                    pending_speaker = ""
                    continue

                speaker = self._parse_standalone_speaker(paragraph, character_names)
                if speaker:
                    pending_speaker = speaker
                    continue

                dialogue = None
                if pending_speaker:
                    dialogue = {"character": pending_speaker, "line": paragraph}
                    pending_speaker = ""
                else:
                    dialogue = self._parse_dialogue(paragraph, character_names)

                if dialogue:
                    chunk_type = "dialogue"
                    chunk_characters = [dialogue["character"]]
                    content = f"{dialogue['character']}：{dialogue['line']}"
                else:
                    chunk_characters = [name for name in character_names if self._mentions_character(paragraph, name)]
                    chunk_type = self._infer_chunk_type(paragraph, mode)
                    content = paragraph

                paragraph_index += 1
                chunks.append(
                    {
                        "script_id": script_id,
                        "chunk_id": f"scene_{scene_index:03d}_{chunk_type}_{paragraph_index:03d}",
                        "scene_id": scene["scene_id"],
                        "source": self._format_chunk_source(scene, chunk_type, paragraph_index),
                        "scene": scene.get("heading") or scene.get("scene_number") or "",
                        "location": scene.get("location") or "",
                        "time": scene.get("time") or "",
                        "characters": chunk_characters,
                        "chunk_type": chunk_type,
                        "content": content,
                        "emotion_tags": self._find_tags(content, self.EMOTION_WORDS),
                        "visual_tags": self._find_tags(content, self.VISUAL_WORDS),
                    }
                )
        return chunks

    def _iter_scene_paragraphs(self, lines: list[str]) -> list[str]:
        paragraphs: list[str] = []
        for line in lines:
            stripped = self._clean_inline_markdown(line.strip())
            if not stripped or self._is_rule_line(stripped):
                continue
            paragraphs.append(stripped)
        return paragraphs

    def _split_scene_heading(self, heading: str) -> tuple[str, str]:
        clean = heading.strip()
        dotted_parts = self._split_scene_heading_parts(clean)
        if len(dotted_parts) >= 2 and self._is_time_label(dotted_parts[-1]):
            return "·".join(dotted_parts[:-1]).strip() or "未明确地点", dotted_parts[-1]

        parts = clean.split()
        if len(parts) >= 2 and parts[-1] in self.TIME_WORDS:
            return " ".join(parts[:-1]).strip() or "未明确地点", parts[-1]
        if len(parts) >= 2 and self._is_time_label(parts[-1]):
            return " ".join(parts[:-1]).strip() or "未明确地点", parts[-1]
        return clean or "未明确地点", ""

    def _split_scene_heading_parts(self, heading: str) -> list[str]:
        parts: list[str] = []
        current: list[str] = []
        depth = 0
        for char in heading:
            if char in "（(":
                depth += 1
            elif char in "）)" and depth > 0:
                depth -= 1
            if char in "·|｜/" and depth == 0:
                part = "".join(current).strip()
                if part:
                    parts.append(part)
                current = []
                continue
            current.append(char)
        part = "".join(current).strip()
        if part:
            parts.append(part)
        return parts

    def _is_time_label(self, value: str) -> bool:
        clean = value.strip()
        if clean in self.TIME_WORDS:
            return True
        return bool(
            re.match(
                r"^(?:白日|白天|夜晚|雨日|雨夜|雨天|下雨|小雨|大雨|暴雨|晴天|阴天|雪日|雪夜|雪天|下雪|黎明|拂晓|黄昏|傍晚|清晨|早晨|凌晨|上午|中午|下午|午前|午后|深夜|日间|日|夜|早|晨|午|晚|晴|阴)(?:[（(].*)?$",
                clean,
            )
        )

    def _extract_gender(self, description: str) -> str:
        if re.search(r"(^|[，,、\s])男([，,、\s]|$)", description):
            return "男"
        if re.search(r"(^|[，,、\s])女([，,、\s]|$)", description):
            return "女"
        return ""

    def _extract_age(self, description: str) -> int | None:
        match = re.search(r"(\d{1,3})\s*岁", description)
        if not match:
            return None
        age = int(match.group(1))
        return age if 0 < age < 130 else None

    def _parse_dialogue(self, paragraph: str, character_names: list[str]) -> dict[str, str] | None:
        match = re.match(r"^\*\*(?P<name>[^*]+?)\*\*\s*[：:]\s*(?P<line>.+)$", paragraph)
        if match:
            return {
                "character": self._normalize_character_name(match.group("name")),
                "line": match.group("line").strip(),
            }

        normalized_paragraph = self._normalize_character_name(paragraph)
        for name in character_names:
            if normalized_paragraph.startswith(f"{name}：") or normalized_paragraph.startswith(f"{name}:"):
                return {"character": name, "line": normalized_paragraph[len(name) + 1 :].strip()}
        return None

    def _parse_standalone_speaker(self, paragraph: str, character_names: list[str]) -> str:
        clean = self._normalize_character_name(paragraph)
        if len(clean) > 18:
            return ""
        for name in character_names:
            if clean == name:
                return name
            if re.fullmatch(re.escape(name) + r"[（(][^)）]{1,12}[)）]", clean):
                return name
        return ""

    def _infer_chunk_type(self, content: str, mode: str) -> str:
        if any(word in content for word in ["剑", "拳", "脚", "点穴", "狮吼", "刺", "踢", "残影"]):
            return "battle_action" if any(word in content for word in ["叶孤城", "剑", "决战"]) else "action"
        if any(word in content for word in self.ACTION_WORDS):
            return "action"
        if any(word in content for word in ["道具", "长剑", "秘籍", "手电筒", "山门", "旗帜"]):
            return "prop"
        if any(word in content for word in self.EMOTION_WORDS):
            return "emotion"
        return mode or "plot"

    def _is_action_marker(self, paragraph: str) -> bool:
        return "【动作】" in paragraph or paragraph.strip() in {"动作", "【动作】"}

    def _format_scene_source(self, act: str, scene_number: str, location: str) -> str:
        parts = [part for part in [act, scene_number, location] if part]
        return " / ".join(parts)

    def _format_chunk_source(self, scene: dict[str, Any], chunk_type: str, index: int) -> str:
        type_label = {
            "scene_description": "场景描述",
            "character_description": "人物描述",
            "dialogue": "对白",
            "action": "动作段落",
            "battle_action": "战斗动作",
            "emotion": "情绪段落",
            "prop": "道具段落",
            "plot": "剧情段落",
        }.get(chunk_type, chunk_type)
        return f"{scene.get('heading') or scene.get('scene_number')} / {type_label} {index}"

    def _find_tags(self, content: str, candidates: list[str]) -> list[str]:
        return [word for word in candidates if word in content][:8]

    def _extract_query_terms(self, text: str) -> list[str]:
        terms = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", text or "")
        stop_terms = {"生成", "提示词", "适合", "要求", "一个", "这个", "通用", "真人", "写实"}
        return [term for term in terms if term not in stop_terms][:24]

    def _score_chunk(
        self,
        chunk: dict[str, Any],
        request: ScriptPromptRequest,
        query_terms: list[str],
    ) -> int:
        target = self._normalize_character_name(request.target or "")
        generation_type = request.generation_type or "character"
        content = str(chunk.get("content") or "")
        source = str(chunk.get("source") or "")
        normalized_content = self._normalize_character_name(content)
        normalized_source = self._normalize_character_name(source)
        normalized_scene = self._normalize_character_name(str(chunk.get("scene") or ""))
        normalized_location = self._normalize_character_name(str(chunk.get("location") or ""))
        characters = {self._normalize_character_name(str(name)) for name in (chunk.get("characters") or [])}
        chunk_type = str(chunk.get("chunk_type") or "")
        score = 0

        if target:
            if target in characters:
                score += 42
            if target in normalized_content:
                score += 32
            if target in normalized_source or target in normalized_scene:
                score += 28
            if target in normalized_location:
                score += 24
            if generation_type in {"character", "scene"} and score == 0:
                return 0

        type_weights = self._type_weights(generation_type)
        score += type_weights.get(chunk_type, 0)
        for term in query_terms:
            normalized_term = self._normalize_character_name(term)
            if normalized_term and (normalized_term in normalized_content or normalized_term in normalized_source):
                score += 5

        if chunk.get("emotion_tags") and generation_type == "character":
            score += 5
        if chunk.get("visual_tags") and generation_type == "scene":
            score += 5
        return score

    def _type_weights(self, generation_type: str) -> dict[str, int]:
        if generation_type == "character":
            return {
                "character_description": 60,
                "action": 10,
                "battle_action": 10,
                "dialogue": 8,
                "emotion": 8,
                "plot": 4,
            }
        if generation_type == "scene":
            return {
                "scene_description": 22,
                "prop": 12,
                "action": 9,
                "battle_action": 9,
                "emotion": 7,
                "dialogue": 2,
            }
        return {}

    def _public_reference(
        self,
        chunk: dict[str, Any],
        request: ScriptPromptRequest,
    ) -> dict[str, Any]:
        return {
            "chunk_id": chunk.get("chunk_id"),
            "source": chunk.get("source"),
            "quote": chunk.get("content"),
            "chunk_type": chunk.get("chunk_type"),
            "characters": chunk.get("characters") or [],
            "usage": self._reference_usage(chunk, request),
        }

    def _reference_usage(self, chunk: dict[str, Any], request: ScriptPromptRequest) -> str:
        chunk_type = chunk.get("chunk_type")
        generation_type = request.generation_type
        if chunk_type == "character_description":
            return "用于确定人物身份、年龄、基础性格和角色定位"
        if generation_type == "character":
            return "用于提取角色动作、情绪、气质和成长反差"
        if generation_type == "scene":
            return "用于确定地点、时间、环境元素、环境痕迹和氛围"
        return "用于补充环境氛围和画面依据"

    def _is_cold_open_scene_text(self, value: str) -> bool:
        return any(term in (value or "") for term in self.COLD_OPEN_SCENE_TERMS)

    def _slugify(self, value: str) -> str:
        ascii_part = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_").lower()
        if ascii_part:
            return ascii_part[:48]
        digest = sha1(value.encode("utf-8")).hexdigest()[:10]
        return f"script_{digest}"


script_prompt_service = ScriptPromptService()
