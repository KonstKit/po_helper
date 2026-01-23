from __future__ import annotations

from typing import Any, Dict, List

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

    def get_input_artifacts(self, node_id: str) -> List[Artifact]:
        """Получить все входные артефакты для ноды."""
        all_inputs = []

        incoming = self.incoming_edges.get(node_id, [])

        for edge in incoming:
            source_id = edge["source"]
            source_artifacts = self.node_outputs.get(source_id, [])
            all_inputs.extend(source_artifacts)

        return all_inputs
