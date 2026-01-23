"""
Traceability Rule Execution Engine (compat wrapper).

The implementation moved to app.services.traceability.engine.engine.
"""

from app.services.traceability.engine.engine import RuleExecutionEngine
from app.services.traceability.engine.validators import InputValidator

__all__ = ["RuleExecutionEngine", "InputValidator"]
