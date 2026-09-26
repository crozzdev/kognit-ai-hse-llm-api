"""Provider factory: select the active implementation from configuration (R11.23).

``build_provider`` returns the ``ModelProvider`` named by
``settings.model_provider``. Concrete transport modules are imported lazily so
that importing this module pulls in no provider SDK unless that provider is
selected (import boundary B2, R15.17).
"""

from typing import TYPE_CHECKING

from kognit_llm.providers.base import ModelProvider

if TYPE_CHECKING:
    from kognit_llm.config.secrets import SecretResolver
    from kognit_llm.config.settings import Settings

__all__ = ["build_provider"]


def build_provider(
    settings: "Settings", secrets: "SecretResolver"
) -> ModelProvider:
    """Construct the configured provider (R11.23).

    A new provider implementation is added here and in ``Settings`` only, with no
    change to the agent, scope guard, intent classifier, generator or synthesizer
    (R11.24).
    """
    provider = settings.model_provider
    if provider == "stub":
        from kognit_llm.providers.stub import StubProvider

        return StubProvider()
    if provider == "openai_compatible":
        from kognit_llm.providers.openai_compatible import OpenAICompatibleProvider

        return OpenAICompatibleProvider(settings=settings, secrets=secrets)
    if provider == "bedrock":
        from kognit_llm.providers.bedrock import BedrockProvider

        return BedrockProvider(settings=settings, secrets=secrets)
    raise ValueError(f"unknown model provider: {provider}")
