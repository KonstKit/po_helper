from sqlalchemy import Column, Integer, String, Boolean, JSON, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class TraceabilityRule(Base):
    """
    Traceability rule configuration stored as React Flow JSON.
    """
    __tablename__ = "traceability_rules"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)

    # React Flow data
    flow_json = Column(JSON, nullable=False)  # { nodes: [], edges: [] }

    # Metadata
    enabled = Column(Boolean, default=True, nullable=False)
    category = Column(String(50), default='custom')  # basic, advanced, custom
    tags = Column(JSON, default=list)  # ["git", "jira", "bidirectional"]

    # Execution stats
    total_executions = Column(Integer, default=0)
    successful_executions = Column(Integer, default=0)
    failed_executions = Column(Integer, default=0)
    last_executed_at = Column(DateTime(timezone=True), nullable=True)

    # Ownership
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    created_by = relationship("User", back_populates="traceability_rules")
    project = relationship("Project", back_populates="traceability_rules")
    executions = relationship("TraceabilityRuleExecution", back_populates="rule", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<TraceabilityRule(id={self.id}, name='{self.name}', enabled={self.enabled})>"


class TraceabilityRuleExecution(Base):
    """
    Log of rule execution attempts.
    """
    __tablename__ = "traceability_rule_executions"

    id = Column(Integer, primary_key=True, index=True)
    rule_id = Column(Integer, ForeignKey("traceability_rules.id"), nullable=False, index=True)

    # Execution metadata
    status = Column(String(20), nullable=False)  # success, failed, partial
    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Results
    links_created = Column(Integer, default=0)
    links_updated = Column(Integer, default=0)
    artifacts_processed = Column(Integer, default=0)

    # Error tracking
    error_message = Column(Text, nullable=True)
    error_details = Column(JSON, nullable=True)

    # Execution context
    execution_context = Column(JSON, nullable=True)  # filters, date ranges, etc.

    # Relationship
    rule = relationship("TraceabilityRule", back_populates="executions")

    def __repr__(self):
        return f"<TraceabilityRuleExecution(id={self.id}, rule_id={self.rule_id}, status='{self.status}')>"
