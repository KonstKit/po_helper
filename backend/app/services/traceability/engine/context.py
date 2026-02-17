from __future__ import annotations

from typing import Any, Dict, List, Set

from sqlalchemy.orm import Session

from app.models.traceability import Artifact, ArtifactLink


class ExecutionContext:
    """Контекст выполнения правила - хранит промежуточные данные между нодами."""

    def __init__(self, rule_id: int, db: Session, edges: List[Dict[str, Any]]):
        self.rule_id = rule_id
        self.db = db
        self.edges = edges
        self.node_outputs: Dict[str, List[Artifact]] = {}
        self.links_created: List[ArtifactLink] = []
        self.processed_artifact_ids: Set[int] = set()
        self.errors: List[str] = []
        self.warnings: List[str] = []

        self.incoming_edges: Dict[str, List[Dict[str, Any]]] = {}
        for edge in edges:
            target = edge["target"]
            if target not in self.incoming_edges:
                self.incoming_edges[target] = []
            self.incoming_edges[target].append(edge)

    def set_node_output(self, node_id: str, artifacts: List[Artifact]) -> None:
        """Сохранить результат выполнения ноды."""
        self.node_outputs[node_id] = artifacts
        self._track_artifacts(artifacts)

    def get_node_output(self, node_id: str) -> List[Artifact]:
        """Получить результат выполнения ноды."""
        return self.node_outputs.get(node_id, [])

    def add_link(self, link: ArtifactLink) -> None:
        """Добавить созданную связь."""
        self.links_created.append(link)

    def add_error(self, message: str) -> None:
        """Добавить ошибку."""
        self.errors.append(message)

    def add_warning(self, message: str) -> None:
        """Добавить предупреждение."""
        self.warnings.append(message)

    def set_node_output_with_handle(
        self, node_id: str, handle: str, artifacts: List[Artifact]
    ) -> None:
        """Сохранить результат выполнения ноды для конкретного выходного handle."""
        key = f"{node_id}_{handle}"
        self.node_outputs[key] = artifacts
        self._track_artifacts(artifacts)

    def _track_artifacts(self, artifacts: List[Artifact]) -> None:
        for artifact in artifacts:
            artifact_id = getattr(artifact, "id", None)
            if isinstance(artifact_id, int):
                self.processed_artifact_ids.add(artifact_id)

    def get_input_artifacts(self, node_id: str) -> List[Artifact]:
        """Получить все входные артефакты для ноды.

        Учитывает sourceHandle для корректной работы ветвления (DecisionNode).
        Если edge имеет sourceHandle, ищем выход по ключу {source}_{sourceHandle}.
        """
        all_inputs = []

        incoming = self.incoming_edges.get(node_id, [])

        for edge in incoming:
            source_id = edge["source"]
            source_handle = edge.get("sourceHandle")

            # Try handle-specific output first (for DecisionNode branches)
            if source_handle:
                handle_key = f"{source_id}_{source_handle}"
                if handle_key in self.node_outputs:
                    all_inputs.extend(self.node_outputs[handle_key])
                    continue

            # Fall back to node output without handle
            source_artifacts = self.node_outputs.get(source_id, [])
            all_inputs.extend(source_artifacts)

        return all_inputs
