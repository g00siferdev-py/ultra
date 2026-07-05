from ultra.llm.anthropic import AnthropicProvider
from ultra.llm.base import LLMProvider
from ultra.llm.openai import OpenAIProvider
from ultra.config import Config


def create_provider(config: Config) -> LLMProvider:
    if config.provider == "openai":
        return OpenAIProvider(api_key=config.api_key, model=config.model)
    if config.provider == "anthropic":
        return AnthropicProvider(api_key=config.api_key, model=config.model)
    if config.provider == "ollama":
        headers: dict[str, str] = {}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        return OpenAIProvider(
            api_key="unused",
            model=config.model,
            base_url=config.ollama_base_url,
            default_headers=headers or None,
        )
    raise ValueError(f"Unsupported provider: {config.provider}")
