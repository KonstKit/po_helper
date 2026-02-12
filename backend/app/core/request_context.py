from __future__ import annotations

import contextvars
from typing import Optional


_request_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "request_id", default=None
)
_actor_id_var: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar(
    "actor_id", default=None
)


def set_request_id(request_id: Optional[str]) -> contextvars.Token[Optional[str]]:
    return _request_id_var.set(request_id)


def reset_request_id(token: contextvars.Token[Optional[str]]) -> None:
    _request_id_var.reset(token)


def get_request_id() -> Optional[str]:
    return _request_id_var.get()


def set_actor_id(actor_id: Optional[int]) -> contextvars.Token[Optional[int]]:
    return _actor_id_var.set(actor_id)


def reset_actor_id(token: contextvars.Token[Optional[int]]) -> None:
    _actor_id_var.reset(token)


def get_actor_id() -> Optional[int]:
    return _actor_id_var.get()
