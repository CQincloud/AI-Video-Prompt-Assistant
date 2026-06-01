"""DashScope image understanding and image generation helpers."""

from __future__ import annotations

import asyncio
import base64
import time
from typing import Any

import httpx
from loguru import logger

from app.config import config


class ImageAIError(Exception):
    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class ImageAIService:
    """Call DashScope-compatible vision and image generation APIs."""

    TRANSIENT_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}

    def _http_timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            timeout=config.dashscope_request_timeout_seconds,
            connect=config.dashscope_connect_timeout_seconds,
        )

    def _request_attempts(self, retry: bool) -> int:
        if not retry:
            return 1
        return config.dashscope_max_retries + 1

    def _headers(self) -> dict[str, str]:
        if not config.dashscope_api_key:
            raise ImageAIError("DashScope API Key 未配置", 503)
        return {
            "Authorization": f"Bearer {config.dashscope_api_key}",
            "Content-Type": "application/json",
        }

    async def analyze_images(
        self,
        prompt: str,
        images: list[dict[str, Any]],
    ) -> str:
        if not images:
            raise ImageAIError("请先上传需要分析的图片", 400)

        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": prompt
                or "请把图片内容分析成 AI 视频提示词资产，并整理出人物、表情、动作、场景、镜头、光影、视觉色卡和可复用视频提示词。",
            }
        ]
        for image in images:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": self._data_url(
                            image["content"],
                            image["mime_type"],
                        )
                    },
                }
            )

        payload = {
            "model": config.dashscope_vision_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是「火宝 AI 视频提示词助手」，专门负责把图片内容分析成 AI 视频生成资产，默认面向 AI 真人视频和写实视频。\n\n"
                        "你需要从图片中提取：\n"
                        "1. 角色信息：性别、年龄感、服装、发型、身份感、性格气质；\n"
                        "2. 表情信息：眼神、眉毛、嘴角、面部情绪、隐藏情绪；\n"
                        "3. 动作信息：姿态、手势、身体重心、运动趋势；\n"
                        "4. 场景信息：地点、时间、天气、空间层次、道具；\n"
                        "5. 镜头语言：景别、角度、构图、光影、焦点；\n"
                        "6. 影像风格：写实程度、色彩、质感、氛围、电影感、真实光影；\n"
                        "7. 视觉色卡：提取主色、辅助色、强调色、阴影色、光源色温和整体色调，用于后续场景或系列画面统一；\n"
                        "8. 可复用提示词：把图片转成图生视频、文生视频、首帧图、关键帧提示词；\n"
                        "9. 视频用途：判断这张图适合作为人物参考、场景参考、首帧图、封面图、分镜图还是剧情关键帧。\n\n"
                        "输出格式：\n"
                        "【图片内容概述】\n"
                        "【角色设定提取】\n"
                        "【表情与情绪】\n"
                        "【动作与姿态】\n"
                        "【场景与氛围】\n"
                        "【镜头与构图】\n"
                        "【视觉色卡与光影】\n"
                        "【影像风格关键词】\n"
                        "【可直接复用的 AI 视频提示词】\n"
                        "【适合用于 AI 视频的用途】\n\n"
                        "如果图片中某项信息无法判断，请写“未识别”或“需要用户补充”，不要编造。"
                        "【可直接复用的 AI 视频提示词】必须是用户可以复制的完整生成区块，"
                        "包含“正向提示词”和“负面提示词”；不要让生成必需信息只停留在分析说明里。"
                        "色卡只作为分析和场景生成约束，不要要求画面里出现色卡块、文字或信息栏。"
                    ),
                },
                {
                    "role": "system",
                    "content": (
                        "当图片包含人物，或用户要求分析图片生成提示词、人物设定、角色模板时，"
                        "必须额外输出可复用的角色三视图设定提示词。"
                        "该提示词必须放在可复制区内，并包含“正向提示词”和“负面提示词”。"
                        "规范输出人物角色模板提示词时必须强制描述一张图同时包含所有内容："
                        "面部特写放在最左边，占满 1/3 位置，是超大面部特写，"
                        "中性表情，直视镜头，纯白背景，完整展示五官、发型、妆容、头饰、耳饰和标志性识别点；"
                        "三视图放在右边 2/3，要3个完整全身视图，依次展示正视图、侧视图、后视图，"
                        "标准自然站姿，无动作表演，无情绪表演，完整展示角色全身形象，无裁切，纯白背景；"
                        "整张图不得出现任何文字描述、标题、标签、水印或信息栏。"
                        "角色描述必须包含人设记忆点，并把记忆点转译为脸型、眼型、发型、体型、服装剪影和标志性特征。"
                        "人物三视图提示词不要单独输出色卡板块；颜色只融入发型、服装、头饰、妆容和配饰描述。"
                        "不要默认加入活人感、毛孔、皮肤微纹理、痘印、油光等皮肤细节；"
                        "只有用户明确要求禁塑料感、真人感或写实皮肤时，才加入简短真实皮肤关键词。"
                        "负面提示词必须包含：不要文字、标题、标签、水印、信息栏、裁切身体、缺脚、视图不完整、"
                        "三视图脸不一致、服装不一致、发型不一致、随机新增配饰、手持道具、背景场景、夸张动作、夸张表情。"
                    ),
                },
                {"role": "user", "content": content},
            ],
            "temperature": 0.3,
            "stream": False,
        }

        async with httpx.AsyncClient(timeout=self._http_timeout()) as client:
            data = await self._request_json(
                client,
                "POST",
                f"{config.dashscope_base_url.rstrip('/')}/chat/completions",
                headers=self._headers(),
                json=payload,
            )

        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise ImageAIError("图片识别结果解析失败", 502) from exc

    async def generate_images(
        self,
        prompt: str,
        size: str = "1024*1024",
        count: int = 1,
        style: str | None = None,
    ) -> dict[str, Any]:
        if not prompt.strip():
            raise ImageAIError("请输入图片生成提示词", 400)

        final_prompt = prompt.strip()
        if style:
            final_prompt = f"{final_prompt}，画风：{style.strip()}"

        create_payload = {
            "model": config.dashscope_image_generation_model,
            "input": {"prompt": final_prompt},
            "parameters": {
                "size": size,
                "n": max(1, min(count, 4)),
            },
        }
        headers = {
            **self._headers(),
            "X-DashScope-Async": "enable",
        }

        async with httpx.AsyncClient(timeout=self._http_timeout()) as client:
            task_data = await self._request_json(
                client,
                "POST",
                (
                    f"{config.dashscope_task_base_url.rstrip('/')}"
                    "/services/aigc/text2image/image-synthesis"
                ),
                headers=headers,
                json=create_payload,
            )
            task_id = self._extract_task_id(task_data)
            result_data = await self._poll_image_task(client, task_id)

        images = self._extract_generated_images(result_data)
        if not images:
            raise ImageAIError("图片生成完成，但没有返回图片地址", 502)

        return {
            "taskId": task_id,
            "prompt": final_prompt,
            "size": size,
            "count": len(images),
            "images": images,
        }

    async def _poll_image_task(
        self,
        client: httpx.AsyncClient,
        task_id: str,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + config.image_generation_poll_timeout_seconds
        task_url = f"{config.dashscope_task_base_url.rstrip('/')}/tasks/{task_id}"
        headers = self._headers()

        while time.monotonic() < deadline:
            await asyncio.sleep(config.image_generation_poll_interval_seconds)
            data = await self._request_json(
                client,
                "GET",
                task_url,
                headers=headers,
                retry=True,
            )
            output = data.get("output") or {}
            status = (
                output.get("task_status")
                or output.get("status")
                or data.get("task_status")
                or data.get("status")
                or ""
            ).upper()

            if status in {"SUCCEEDED", "SUCCESS", "COMPLETED"}:
                return data
            if status in {"FAILED", "CANCELED", "UNKNOWN"}:
                message = output.get("message") or data.get("message") or "unknown"
                logger.warning(f"DashScope image task failed: status={status}, message={message}")
                raise ImageAIError("图片生成失败，请调整提示词后重试", 502)

        raise ImageAIError("图片生成超时，请稍后重试", 504)

    def _extract_task_id(self, data: dict[str, Any]) -> str:
        output = data.get("output") or {}
        task_id = output.get("task_id") or data.get("task_id")
        if not task_id:
            raise ImageAIError("图片生成任务创建失败", 502)
        return str(task_id)

    def _extract_generated_images(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        output = data.get("output") or data
        candidates = (
            output.get("results")
            or output.get("images")
            or output.get("result")
            or output.get("data")
            or []
        )
        if isinstance(candidates, dict):
            candidates = [candidates]
        if not isinstance(candidates, list):
            candidates = []

        images: list[dict[str, Any]] = []
        for index, item in enumerate(candidates, start=1):
            if isinstance(item, str):
                url = item
            elif isinstance(item, dict):
                url = item.get("url") or item.get("image_url") or item.get("oss_url")
            else:
                url = None
            if url:
                images.append({"url": url, "index": index})

        single_url = output.get("url") or output.get("image_url") or output.get("result_url")
        if single_url and all(image["url"] != single_url for image in images):
            images.append({"url": single_url, "index": len(images) + 1})

        return images

    def _data_url(self, content: bytes, mime_type: str) -> str:
        encoded = base64.b64encode(content).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    async def _request_json(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any] | None = None,
        retry: bool = False,
    ) -> dict[str, Any]:
        attempts = self._request_attempts(retry)
        last_error: Exception | None = None

        for attempt in range(attempts):
            try:
                response = await client.request(method, url, headers=headers, json=json)
                if (
                    retry
                    and response.status_code in self.TRANSIENT_STATUS_CODES
                    and attempt < attempts - 1
                ):
                    await asyncio.sleep(min(2 ** attempt, 4))
                    continue

                self._raise_for_response(response)
                try:
                    return response.json()
                except ValueError as exc:
                    raise ImageAIError("AI 服务响应解析失败，请稍后重试", 502) from exc
            except httpx.TimeoutException as exc:
                last_error = exc
                if attempt < attempts - 1:
                    await asyncio.sleep(min(2 ** attempt, 4))
                    continue
                raise ImageAIError("AI 服务请求超时，请稍后重试", 504) from exc
            except httpx.TransportError as exc:
                last_error = exc
                if attempt < attempts - 1:
                    await asyncio.sleep(min(2 ** attempt, 4))
                    continue
                raise ImageAIError("AI 服务网络异常，请稍后重试", 502) from exc

        raise ImageAIError("AI 服务暂时不可用，请稍后重试", 502) from last_error

    def _raise_for_response(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return

        upstream_message = response.text
        try:
            data = response.json()
            upstream_message = (
                data.get("message")
                or data.get("error", {}).get("message")
                or upstream_message
            )
        except ValueError:
            pass

        logger.warning(
            f"DashScope image API failed: status={response.status_code}, "
            f"upstream_message={str(upstream_message)[:160]}"
        )

        if response.status_code in {401, 403}:
            message = "AI 服务鉴权失败，请检查服务配置"
        elif response.status_code == 429:
            message = "AI 服务请求过于频繁，请稍后重试"
        elif response.status_code >= 500:
            message = "AI 服务暂时不可用，请稍后重试"
        else:
            message = "AI 服务请求失败，请检查输入后重试"

        raise ImageAIError(message, response.status_code)


image_ai_service = ImageAIService()
