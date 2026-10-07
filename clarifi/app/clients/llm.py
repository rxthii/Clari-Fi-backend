import logging

from app.core.errors import AppError

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self, settings):
        self.settings = settings

    def models(self):
        return list(dict.fromkeys([self.settings.openrouter_model, *self.settings.fallback_models]))

    async def invoke(self, messages, tools):
        if not self.settings.openrouter_api_key:
            raise AppError("AI_UNAVAILABLE", "The assistant is temporarily unavailable.", 503)
        from langchain_openai import ChatOpenAI
        last_error = None
        for model in self.models():
            try:
                llm = ChatOpenAI(model=model, api_key=self.settings.openrouter_api_key, base_url="https://openrouter.ai/api/v1", temperature=0.2, max_retries=0, timeout=25)
                return await llm.bind_tools(tools, parallel_tool_calls=False).ainvoke(messages)
            except Exception as exc:
                last_error = exc
                logger.warning("LLM model attempt failed model=%s error_type=%s", model, type(exc).__name__)
        raise AppError("AI_UNAVAILABLE", "The assistant is temporarily unavailable.", 503) from last_error

