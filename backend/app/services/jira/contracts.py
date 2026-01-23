from __future__ import annotations

from typing import Dict, Optional, Protocol

import requests


class IJiraTransport(Protocol):
    base_url: Optional[str]

    def headers(self) -> Dict[str, str]: ...

    def request(self, method: str, endpoint: str, **kwargs) -> requests.Response: ...

    def get(self, endpoint: str, **kwargs) -> requests.Response: ...

    def basic_auth_tuple(self) -> Optional[tuple[str, str]]: ...
