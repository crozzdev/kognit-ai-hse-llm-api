"""Dependency bundle shared by the graph nodes (B4).

Nodes depend only on component *interfaces*, never on their internals. The graph
builder constructs one ``NodeDeps`` per execution environment and passes it to
every node factory, so a node never imports a concrete provider, executor or
store — it receives them here.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kognit_llm.config.settings import Settings
    from kognit_llm.data.executor import WarehouseExecutor
    from kognit_llm.memory.store import ConversationStore
    from kognit_llm.providers.base import ModelProvider
    from kognit_llm.schema.allowlist import AllowList

__all__ = ["NodeDeps"]


@dataclass(frozen=True, slots=True)
class NodeDeps:
    """Component interfaces the nodes use, assembled once per environment."""

    settings: "Settings"
    provider: "ModelProvider"
    executor: "WarehouseExecutor"
    store: "ConversationStore"
    allowlist: "AllowList"
