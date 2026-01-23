from __future__ import annotations

from typing import Dict, Optional

from app.services.traceability.engine.nodes.base import NodeExecutor


class ExecutorRegistry:
    def __init__(self) -> None:
        self._by_type: Dict[str, NodeExecutor] = {}

    def register(self, node_type: str, executor: NodeExecutor) -> None:
        self._by_type[node_type] = executor

    def get(self, node_type: Optional[str]) -> Optional[NodeExecutor]:
        if not node_type:
            return None
        return self._by_type.get(node_type)
