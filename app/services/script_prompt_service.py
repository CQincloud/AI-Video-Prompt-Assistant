"""Script-based prompt reference service.

This module implements the MVP flow for turning a pasted screenplay into
referenced prompt context. It intentionally keeps script storage out of the
first version: the caller sends script text for parsing, then sends the parsed
structure back when retrieving references for the normal chat generator.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha1
from typing import Any


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
        "storyboard": "分镜提示词",
        "action": "动作提示词",
        "plot": "剧情提示词",
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
    TIME_WORDS = {
        "日",
        "夜",
        "晨",
        "午",
        "晚",
        "清晨",
        "上午",
        "中午",
        "下午",
        "黄昏",
        "傍晚",
        "深夜",
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

    def retrieve_references(
        self,
        parsed_script: dict[str, Any],
        request: ScriptPromptRequest,
        *,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        chunks = list(parsed_script.get("chunks") or [])
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

    def _normalize_text(self, text: str) -> str:
        return (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()

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

        for line in lines:
            clean = line.strip()
            if re.match(r"^#{1,6}\s*人物表", clean):
                in_character_section = True
                continue
            if in_character_section and re.match(r"^#{1,6}\s+", clean):
                break
            if not in_character_section:
                continue

            match = re.match(
                r"^\s*[-*]\s*(?:\*\*)?(?P<name>[^*：:]+?)(?:\*\*)?\s*[：:]\s*(?P<desc>.+)$",
                line,
            )
            if not match:
                continue
            name = match.group("name").strip()
            description = match.group("desc").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            characters.append(
                {
                    "name": name,
                    "description": description,
                    "gender": self._extract_gender(description),
                    "age": self._extract_age(description),
                }
            )
        return characters

    def _extract_scenes(
        self,
        script_text: str,
        characters: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        lines = script_text.splitlines()
        current_act = ""
        current_scene: dict[str, Any] | None = None
        scenes: list[dict[str, Any]] = []

        for line in lines:
            clean = line.strip()
            act_match = re.match(r"^##\s+(第.+幕.+)$", clean)
            if act_match:
                current_act = act_match.group(1).strip()
                continue

            scene_match = re.match(r"^#{1,6}\s*(场景[^\s]+)\s+(.+?)\s*$", clean)
            if scene_match:
                if current_scene:
                    scenes.append(current_scene)
                scene_label = scene_match.group(1).strip()
                rest = scene_match.group(2).strip()
                location, time_label = self._split_scene_heading(rest)
                scene_id = f"scene_{len(scenes) + 1:03d}"
                current_scene = {
                    "scene_id": scene_id,
                    "act": current_act,
                    "scene_number": scene_label,
                    "location": location,
                    "time": time_label,
                    "heading": self._format_scene_source(current_act, scene_label, location),
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
            scene["characters"] = [name for name in character_names if name and name in content]
        return scenes

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
            for paragraph in self._iter_scene_paragraphs(scene.get("content_lines") or []):
                if self._is_action_marker(paragraph):
                    mode = "action"
                    continue

                paragraph_index += 1
                dialogue = self._parse_dialogue(paragraph, character_names)
                if dialogue:
                    chunk_type = "dialogue"
                    chunk_characters = [dialogue["character"]]
                    content = f"{dialogue['character']}：{dialogue['line']}"
                else:
                    chunk_characters = [name for name in character_names if name and name in paragraph]
                    chunk_type = self._infer_chunk_type(paragraph, mode)
                    content = paragraph

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
        current: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                if current:
                    paragraphs.append(" ".join(current).strip())
                    current = []
                continue
            if re.match(r"^---+$", stripped):
                continue
            if self._is_action_marker(stripped):
                if current:
                    paragraphs.append(" ".join(current).strip())
                    current = []
                paragraphs.append(stripped)
                continue
            if re.match(r"^\*\*[^*]+?\*\*\s*[：:]", stripped) and current:
                paragraphs.append(" ".join(current).strip())
                current = []
            current.append(stripped)
        if current:
            paragraphs.append(" ".join(current).strip())
        return paragraphs

    def _split_scene_heading(self, heading: str) -> tuple[str, str]:
        parts = heading.split()
        if len(parts) >= 2 and parts[-1] in self.TIME_WORDS:
            return " ".join(parts[:-1]).strip() or "未明确地点", parts[-1]
        return heading.strip() or "未明确地点", ""

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
            return {"character": match.group("name").strip(), "line": match.group("line").strip()}

        for name in character_names:
            if paragraph.startswith(f"{name}：") or paragraph.startswith(f"{name}:"):
                return {"character": name, "line": paragraph[len(name) + 1 :].strip()}
        return None

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
        target = (request.target or "").strip()
        generation_type = request.generation_type or "plot"
        content = str(chunk.get("content") or "")
        source = str(chunk.get("source") or "")
        characters = set(chunk.get("characters") or [])
        chunk_type = str(chunk.get("chunk_type") or "")
        score = 0

        if target:
            if target in characters:
                score += 42
            if target in content:
                score += 32
            if target in source or target in str(chunk.get("scene") or ""):
                score += 28
            if target in str(chunk.get("location") or ""):
                score += 24
            if generation_type in {"character", "scene", "storyboard", "action"} and score == 0:
                return 0

        type_weights = self._type_weights(generation_type)
        score += type_weights.get(chunk_type, 0)
        for term in query_terms:
            if term and (term in content or term in source):
                score += 5

        if chunk.get("emotion_tags") and generation_type == "character":
            score += 5
        if chunk.get("visual_tags") and generation_type in {"scene", "plot"}:
            score += 5
        if generation_type == "plot":
            score += 2
        return score

    def _type_weights(self, generation_type: str) -> dict[str, int]:
        if generation_type == "character":
            return {
                "character_description": 24,
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
        if generation_type == "storyboard":
            return {
                "scene_description": 16,
                "action": 15,
                "battle_action": 18,
                "dialogue": 8,
                "emotion": 8,
                "plot": 8,
            }
        if generation_type == "action":
            return {
                "action": 22,
                "battle_action": 24,
                "dialogue": 4,
                "emotion": 6,
                "scene_description": 5,
            }
        return {
            "character_description": 10,
            "scene_description": 10,
            "action": 10,
            "battle_action": 10,
            "dialogue": 8,
            "emotion": 8,
            "plot": 6,
        }

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
            return "用于确定地点、时间、环境元素、人物调度和氛围"
        if generation_type == "storyboard":
            return "用于拆分镜头动作、节奏、冲突推进和画面重点"
        if generation_type == "action":
            return "用于提炼动作过程、力量方向、速度感和镜头表现"
        return "用于提炼剧情冲突、人物关系、情绪弧线和结构重点"

    def _slugify(self, value: str) -> str:
        ascii_part = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_").lower()
        if ascii_part:
            return ascii_part[:48]
        digest = sha1(value.encode("utf-8")).hexdigest()[:10]
        return f"script_{digest}"


script_prompt_service = ScriptPromptService()
