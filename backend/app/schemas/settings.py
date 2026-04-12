from typing import Optional
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, field_validator


class IntegrationSettingsBase(BaseModel):
    base_url: Optional[str] = None
    email: Optional[str] = None  # accept empty string; validate upstream if needed
    api_token: Optional[str] = None
    webhook_secret: Optional[str] = (
        None  # for GitHub/GitLab (stored encrypted as part of token bundle)
    )
    use_pat: Optional[bool] = None  # prefer PAT vs Basic when applicable

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None

        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("base_url must be a valid http:// or https:// URL")
        return normalized.rstrip("/")


class IntegrationSettings(IntegrationSettingsBase):
    kind: str
    has_token: bool | None = None
    has_webhook_secret: bool | None = None

    model_config = ConfigDict(from_attributes=True)
