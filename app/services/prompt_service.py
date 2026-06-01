"""Runtime prompt lookup helpers."""

from __future__ import annotations

from app.services.admin_prompt_service import admin_prompt_service


class PromptService:
    def get_active_prompt(self, prompt_key: str, default: str | None = None) -> str:
        return admin_prompt_service.get_active_prompt(prompt_key, default=default)

    def clear_cache(self, prompt_key: str | None = None) -> None:
        admin_prompt_service.clear_cache(prompt_key)


prompt_service = PromptService()
