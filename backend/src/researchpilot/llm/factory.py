"""Build the gateway from configuration. Adding a provider = adding one adapter factory."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from researchpilot.core.settings import Settings
from researchpilot.llm.adapters.base import ProviderAdapter
from researchpilot.llm.adapters.fake import FakeProviderAdapter
from researchpilot.llm.config import LLMConfig, load_llm_config
from researchpilot.llm.gateway import StructuredLLMGateway
from researchpilot.llm.prompts import PromptRegistry


def _anthropic(settings: Settings) -> ProviderAdapter:
    from researchpilot.llm.adapters.anthropic_adapter import AnthropicAdapter

    key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
    return AnthropicAdapter(api_key=key)


ADAPTER_FACTORIES: dict[str, Callable[[Settings], ProviderAdapter]] = {
    "anthropic": _anthropic,
    "fake": lambda _settings: FakeProviderAdapter(),
}


def build_gateway(
    settings: Settings,
    config: LLMConfig | None = None,
    adapters: Mapping[str, ProviderAdapter] | None = None,
) -> StructuredLLMGateway:
    """Adapters are created lazily for the providers the configuration actually uses."""
    config = config or load_llm_config(settings.llm_config_path)
    resolved: dict[str, ProviderAdapter] = dict(adapters or {})
    used = {config.for_task(t).provider for t in config.tasks} | {config.defaults.provider}
    for provider in used - resolved.keys():
        factory = ADAPTER_FACTORIES.get(provider)
        if factory is not None:
            resolved[provider] = factory(settings)
    return StructuredLLMGateway(config, PromptRegistry(settings.prompts_dir), resolved)
