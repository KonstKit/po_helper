from typing import Optional
from pydantic import BaseModel, ConfigDict


class IntegrationSettingsBase(BaseModel):
    base_url: Optional[str] = None
    email: Optional[str] = None  # accept empty string; validate upstream if needed
    api_token: Optional[str] = None
    webhook_secret: Optional[str] = (
        None  # for GitHub/GitLab (stored encrypted as part of token bundle)
    )
    use_pat: Optional[bool] = None  # prefer PAT vs Basic when applicable


class IntegrationSettings(IntegrationSettingsBase):
    kind: str
    has_token: bool | None = None
    has_webhook_secret: bool | None = None

    model_config = ConfigDict(from_attributes=True)
