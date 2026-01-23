from __future__ import annotations

from typing import Any, Dict, List

from app.models.traceability import Artifact
from app.services.traceability.engine.context import ExecutionContext


class NodeExecutor:
    """Базовый класс для выполнения нод."""

    def execute(self, node: Dict[str, Any], context: ExecutionContext) -> List[Artifact]:
        """Выполнить ноду и вернуть список артефактов."""
        raise NotImplementedError
