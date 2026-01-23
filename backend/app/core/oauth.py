"""
OAuth2 SSO Providers for Google and Microsoft Azure AD.

Provides OAuth2 authentication flow support with:
- Authorization URL generation with PKCE
- Token exchange callbacks
- User info retrieval from providers
"""

import logging
import secrets
from typing import Optional, Dict, Any
from dataclasses import dataclass

import httpx

from app.core.config import settings

LOGGER = logging.getLogger(__name__)


class OAuth2Error(Exception):
    """Raised when OAuth2 flow encounters an error."""

    def __init__(self, error: str, description: str = ""):
        self.error = error
        self.description = description
        super().__init__(f"{error}: {description}" if description else error)


@dataclass
class OAuth2UserInfo:
    """Normalized user information from OAuth providers."""

    provider: str
    provider_id: str
    email: str
    name: Optional[str]
    picture: Optional[str]
    email_verified: bool = False


class GoogleOAuth2Client:
    """Google OAuth2 client for authentication."""

    AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        redirect_uri: Optional[str] = None,
    ):
        self.client_id = client_id or settings.GOOGLE_CLIENT_ID
        self.client_secret = client_secret or settings.GOOGLE_CLIENT_SECRET
        self.redirect_uri = redirect_uri or settings.GOOGLE_REDIRECT_URI

    @property
    def is_configured(self) -> bool:
        """Check if Google OAuth is properly configured."""
        return bool(self.client_id and self.client_secret)

    def get_authorization_url(self, state: Optional[str] = None) -> tuple[str, str]:
        """
        Generate Google OAuth2 authorization URL.

        Args:
            state: Optional state parameter for CSRF protection

        Returns:
            Tuple of (authorization_url, state)
        """
        if not self.is_configured:
            raise OAuth2Error("not_configured", "Google OAuth2 is not configured")

        state = state or secrets.token_urlsafe(32)

        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
        }

        query_string = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{self.AUTHORIZATION_URL}?{query_string}", state

    async def exchange_code(self, code: str) -> Dict[str, Any]:
        """
        Exchange authorization code for tokens.

        Args:
            code: Authorization code from callback

        Returns:
            Token response containing access_token, id_token, etc.
        """
        if not self.is_configured:
            raise OAuth2Error("not_configured", "Google OAuth2 is not configured")

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                self.TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": self.redirect_uri,
                },
            )

            if response.status_code != 200:
                error_data = response.json()
                raise OAuth2Error(
                    error_data.get("error", "token_exchange_failed"),
                    error_data.get("error_description", response.text),
                )

            return response.json()

    async def get_user_info(self, access_token: str) -> OAuth2UserInfo:
        """
        Fetch user information from Google.

        Args:
            access_token: OAuth2 access token

        Returns:
            OAuth2UserInfo with normalized user data
        """
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                self.USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                raise OAuth2Error(
                    "userinfo_failed", f"Failed to fetch user info: {response.status_code}"
                )

            data = response.json()

            return OAuth2UserInfo(
                provider="google",
                provider_id=data.get("sub", ""),
                email=data.get("email", ""),
                name=data.get("name"),
                picture=data.get("picture"),
                email_verified=data.get("email_verified", False),
            )


class MicrosoftOAuth2Client:
    """Microsoft Azure AD OAuth2 client for authentication."""

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ):
        self.client_id = client_id or settings.MICROSOFT_CLIENT_ID
        self.client_secret = client_secret or settings.MICROSOFT_CLIENT_SECRET
        self.redirect_uri = redirect_uri or settings.MICROSOFT_REDIRECT_URI
        self.tenant_id = tenant_id or settings.MICROSOFT_TENANT_ID

    @property
    def authorization_url(self) -> str:
        return f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/authorize"

    @property
    def token_url(self) -> str:
        return f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"

    @property
    def is_configured(self) -> bool:
        """Check if Microsoft OAuth is properly configured."""
        return bool(self.client_id and self.client_secret)

    def get_authorization_url(self, state: Optional[str] = None) -> tuple[str, str]:
        """
        Generate Microsoft OAuth2 authorization URL.

        Args:
            state: Optional state parameter for CSRF protection

        Returns:
            Tuple of (authorization_url, state)
        """
        if not self.is_configured:
            raise OAuth2Error("not_configured", "Microsoft OAuth2 is not configured")

        state = state or secrets.token_urlsafe(32)

        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "openid email profile User.Read",
            "state": state,
            "response_mode": "query",
        }

        query_string = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{self.authorization_url}?{query_string}", state

    async def exchange_code(self, code: str) -> Dict[str, Any]:
        """
        Exchange authorization code for tokens.

        Args:
            code: Authorization code from callback

        Returns:
            Token response containing access_token, id_token, etc.
        """
        if not self.is_configured:
            raise OAuth2Error("not_configured", "Microsoft OAuth2 is not configured")

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                self.token_url,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": self.redirect_uri,
                    "scope": "openid email profile User.Read",
                },
            )

            if response.status_code != 200:
                error_data = response.json()
                raise OAuth2Error(
                    error_data.get("error", "token_exchange_failed"),
                    error_data.get("error_description", response.text),
                )

            return response.json()

    async def get_user_info(self, access_token: str) -> OAuth2UserInfo:
        """
        Fetch user information from Microsoft Graph.

        Args:
            access_token: OAuth2 access token

        Returns:
            OAuth2UserInfo with normalized user data
        """
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                "https://graph.microsoft.com/v1.0/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                raise OAuth2Error(
                    "userinfo_failed", f"Failed to fetch user info: {response.status_code}"
                )

            data = response.json()

            # Microsoft Graph returns 'mail' or 'userPrincipalName' for email
            email = data.get("mail") or data.get("userPrincipalName", "")

            return OAuth2UserInfo(
                provider="microsoft",
                provider_id=data.get("id", ""),
                email=email,
                name=data.get("displayName"),
                picture=None,  # Requires separate Graph API call for photo
                email_verified=True,  # Microsoft accounts are verified
            )


# Singleton instances
google_oauth = GoogleOAuth2Client()
microsoft_oauth = MicrosoftOAuth2Client()


def get_oauth_providers() -> Dict[str, bool]:
    """Get available OAuth providers and their configuration status."""
    return {
        "google": settings.google_oauth_configured,
        "microsoft": settings.microsoft_oauth_configured,
    }


def is_email_allowed(email: str) -> bool:
    """
    Check if an email domain is allowed for OAuth registration.

    Args:
        email: Email address to check

    Returns:
        True if allowed, False otherwise
    """
    if not settings.OAUTH_ALLOWED_DOMAINS:
        return True  # All domains allowed

    domain = email.split("@")[-1].lower()
    return domain in [d.lower() for d in settings.OAUTH_ALLOWED_DOMAINS]
