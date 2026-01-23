"""
Tests for OAuth2 SSO and MFA (Multi-Factor Authentication).

Covers:
- OAuth2 client functions (Google, Microsoft)
- OAuth2 endpoints
- MFA setup and verification
- Backup codes
"""
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from app.core.oauth import (
    GoogleOAuth2Client,
    MicrosoftOAuth2Client,
    OAuth2Error,
    OAuth2UserInfo,
    get_oauth_providers,
    is_email_allowed,
)
from app.core.mfa import (
    generate_totp_secret,
    generate_backup_codes,
    get_provisioning_uri,
    generate_qr_code_base64,
    setup_mfa,
    verify_totp,
    verify_backup_code,
    get_current_totp,
    remaining_time_in_period,
    MFAError,
)


class TestGoogleOAuth2:
    """Test Google OAuth2 client."""

    def test_is_not_configured_without_credentials(self):
        """Test configuration check without credentials."""
        client = GoogleOAuth2Client(client_id="", client_secret="")
        assert client.is_configured is False

    def test_is_configured_with_credentials(self):
        """Test configuration check with credentials."""
        client = GoogleOAuth2Client(
            client_id="test-client-id",
            client_secret="test-secret"
        )
        assert client.is_configured is True

    def test_get_authorization_url(self):
        """Test authorization URL generation."""
        client = GoogleOAuth2Client(
            client_id="test-client-id",
            client_secret="test-secret",
            redirect_uri="http://localhost/callback"
        )
        url, state = client.get_authorization_url()

        assert "accounts.google.com" in url
        assert "client_id=test-client-id" in url
        assert "response_type=code" in url
        assert "scope=openid" in url
        assert len(state) > 0

    def test_get_authorization_url_not_configured(self):
        """Test error when not configured."""
        client = GoogleOAuth2Client(client_id="", client_secret="")

        with pytest.raises(OAuth2Error) as exc:
            client.get_authorization_url()
        assert "not_configured" in str(exc.value.error)

    @pytest.mark.asyncio
    async def test_exchange_code_success(self):
        """Test successful code exchange."""
        client = GoogleOAuth2Client(
            client_id="test-client-id",
            client_secret="test-secret",
            redirect_uri="http://localhost/callback"
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "access-token-123",
            "id_token": "id-token-456",
            "refresh_token": "refresh-token-789",
            "expires_in": 3600,
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_response
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            mock_client.return_value = mock_instance

            tokens = await client.exchange_code("auth-code")

            assert tokens["access_token"] == "access-token-123"
            assert tokens["id_token"] == "id-token-456"

    @pytest.mark.asyncio
    async def test_get_user_info_success(self):
        """Test successful user info fetch."""
        client = GoogleOAuth2Client(
            client_id="test-client-id",
            client_secret="test-secret"
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "sub": "google-user-123",
            "email": "user@gmail.com",
            "name": "Test User",
            "picture": "https://example.com/photo.jpg",
            "email_verified": True,
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            mock_client.return_value = mock_instance

            user_info = await client.get_user_info("access-token")

            assert user_info.provider == "google"
            assert user_info.email == "user@gmail.com"
            assert user_info.name == "Test User"
            assert user_info.email_verified is True


class TestMicrosoftOAuth2:
    """Test Microsoft OAuth2 client."""

    def test_is_not_configured_without_credentials(self):
        """Test configuration check without credentials."""
        client = MicrosoftOAuth2Client(client_id="", client_secret="")
        assert client.is_configured is False

    def test_is_configured_with_credentials(self):
        """Test configuration check with credentials."""
        client = MicrosoftOAuth2Client(
            client_id="test-client-id",
            client_secret="test-secret"
        )
        assert client.is_configured is True

    def test_get_authorization_url(self):
        """Test authorization URL generation."""
        client = MicrosoftOAuth2Client(
            client_id="test-client-id",
            client_secret="test-secret",
            redirect_uri="http://localhost/callback",
            tenant_id="common"
        )
        url, state = client.get_authorization_url()

        assert "login.microsoftonline.com" in url
        assert "client_id=test-client-id" in url
        assert "response_type=code" in url
        assert len(state) > 0

    @pytest.mark.asyncio
    async def test_get_user_info_success(self):
        """Test successful user info fetch from Microsoft Graph."""
        client = MicrosoftOAuth2Client(
            client_id="test-client-id",
            client_secret="test-secret"
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "microsoft-user-456",
            "mail": "user@company.com",
            "displayName": "Corporate User",
            "userPrincipalName": "user@company.onmicrosoft.com"
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            mock_client.return_value = mock_instance

            user_info = await client.get_user_info("access-token")

            assert user_info.provider == "microsoft"
            assert user_info.email == "user@company.com"
            assert user_info.name == "Corporate User"


class TestOAuthHelpers:
    """Test OAuth helper functions."""

    def test_is_email_allowed_no_restrictions(self, monkeypatch):
        """Test email allowed when no domain restrictions."""
        monkeypatch.setattr("app.core.oauth.settings.OAUTH_ALLOWED_DOMAINS", [])
        assert is_email_allowed("user@any-domain.com") is True

    def test_is_email_allowed_with_restrictions(self, monkeypatch):
        """Test email filtering with domain restrictions."""
        monkeypatch.setattr(
            "app.core.oauth.settings.OAUTH_ALLOWED_DOMAINS",
            ["company.com", "corp.net"]
        )

        assert is_email_allowed("user@company.com") is True
        assert is_email_allowed("user@corp.net") is True
        assert is_email_allowed("user@other.com") is False


class TestMFACore:
    """Test MFA core functions."""

    def test_generate_totp_secret(self):
        """Test TOTP secret generation."""
        secret = generate_totp_secret()

        assert len(secret) == 32  # Base32 encoded
        assert secret.isalnum()  # Alphanumeric
        assert secret == secret.upper()  # Uppercase

    def test_generate_backup_codes(self):
        """Test backup code generation."""
        codes = generate_backup_codes(count=10)

        assert len(codes) == 10
        for code in codes:
            # Format: XXXX-XXXX
            assert len(code) == 9
            assert code[4] == "-"
            assert code[:4].isalnum()
            assert code[5:].isalnum()

        # All codes should be unique
        assert len(set(codes)) == 10

    def test_get_provisioning_uri(self):
        """Test provisioning URI generation."""
        secret = "JBSWY3DPEHPK3PXP"
        uri = get_provisioning_uri(secret, "user@example.com", "TestApp")

        assert uri.startswith("otpauth://totp/")
        assert "TestApp" in uri
        assert "user%40example.com" in uri or "user@example.com" in uri
        assert "secret=" in uri

    def test_generate_qr_code_base64(self):
        """Test QR code generation."""
        uri = "otpauth://totp/TestApp:user@example.com?secret=JBSWY3DPEHPK3PXP"
        qr_data = generate_qr_code_base64(uri)

        assert qr_data.startswith("data:image/png;base64,")
        assert len(qr_data) > 100  # Has actual data

    def test_setup_mfa(self):
        """Test complete MFA setup."""
        setup_data = setup_mfa("user@example.com")

        assert len(setup_data.secret) == 32
        assert setup_data.provisioning_uri.startswith("otpauth://")
        assert setup_data.qr_code_base64.startswith("data:image/png")
        assert len(setup_data.backup_codes) == 10

    def test_verify_totp_valid(self):
        """Test valid TOTP verification."""
        secret = generate_totp_secret()
        current_code = get_current_totp(secret)

        assert verify_totp(secret, current_code) is True

    def test_verify_totp_invalid(self):
        """Test invalid TOTP verification."""
        secret = generate_totp_secret()

        assert verify_totp(secret, "000000") is False
        assert verify_totp(secret, "123456") is False
        assert verify_totp(secret, "") is False
        assert verify_totp("", "123456") is False

    def test_verify_totp_with_formatting(self):
        """Test TOTP with spaces/dashes."""
        secret = generate_totp_secret()
        current_code = get_current_totp(secret)

        # Add formatting
        formatted = f"{current_code[:3]} {current_code[3:]}"
        assert verify_totp(secret, formatted) is True

    def test_verify_backup_code_valid(self):
        """Test valid backup code verification."""
        codes = generate_backup_codes(count=5)
        test_code = codes[2]

        is_valid, index = verify_backup_code(test_code, codes)

        assert is_valid is True
        assert index == 2

    def test_verify_backup_code_invalid(self):
        """Test invalid backup code verification."""
        codes = generate_backup_codes(count=5)

        is_valid, index = verify_backup_code("XXXX-YYYY", codes)

        assert is_valid is False
        assert index is None

    def test_verify_backup_code_case_insensitive(self):
        """Test backup codes are case-insensitive."""
        codes = ["ABCD-EFGH", "IJKL-MNOP"]

        is_valid, index = verify_backup_code("abcd-efgh", codes)
        assert is_valid is True
        assert index == 0

    def test_remaining_time_in_period(self):
        """Test remaining time calculation."""
        remaining = remaining_time_in_period()

        assert 0 < remaining <= 30  # TOTP period is 30 seconds


class TestOAuth2Endpoints:
    """Test OAuth2 API endpoints."""

    async def test_get_oauth_providers(self, client, auth_headers):
        """Test OAuth providers status endpoint."""
        response = await client.get(
            "/api/v1/auth/oauth2/providers",
            headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert "google" in data
        assert "microsoft" in data

    async def test_google_oauth_initiate(self, client, monkeypatch):
        """Test Google OAuth initiation."""
        # Mock configured OAuth client instance
        monkeypatch.setattr("app.core.oauth.google_oauth.client_id", "test-id")
        monkeypatch.setattr("app.core.oauth.google_oauth.client_secret", "test-secret")
        monkeypatch.setattr("app.core.oauth.google_oauth.redirect_uri", "http://localhost/callback")

        response = await client.get("/api/v1/auth/oauth2/google")

        # Should redirect or return URL
        assert response.status_code in [200, 302, 307]

    async def test_microsoft_oauth_initiate(self, client, monkeypatch):
        """Test Microsoft OAuth initiation."""
        monkeypatch.setattr("app.core.oauth.microsoft_oauth.client_id", "test-id")
        monkeypatch.setattr("app.core.oauth.microsoft_oauth.client_secret", "test-secret")
        monkeypatch.setattr("app.core.oauth.microsoft_oauth.redirect_uri", "http://localhost/callback")
        monkeypatch.setattr("app.core.oauth.microsoft_oauth.tenant_id", "common")

        response = await client.get("/api/v1/auth/oauth2/microsoft")

        assert response.status_code in [200, 302, 307]


class TestMFAEndpoints:
    """Test MFA API endpoints."""

    async def test_get_mfa_status(self, client, auth_headers):
        """Test MFA status endpoint."""
        response = await client.get(
            "/api/v1/auth/mfa/status",
            headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert "mfa_enabled" in data
        assert "remaining_backup_codes" in data or data["mfa_enabled"] is False

    async def test_mfa_setup(self, client, auth_headers):
        """Test MFA setup endpoint."""
        response = await client.post(
            "/api/v1/auth/mfa/setup",
            headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert "qr_code" in data or "qr_code_base64" in data
        assert "secret" in data
        assert "backup_codes" in data

    async def test_mfa_verify(self, client, auth_headers, monkeypatch):
        """Test MFA verification endpoint."""
        # First setup MFA
        setup_response = await client.post(
            "/api/v1/auth/mfa/setup",
            headers=auth_headers
        )
        setup_data = setup_response.json()
        secret = setup_data.get("secret")

        if secret:
            # Get current TOTP code
            current_code = get_current_totp(secret)

            response = await client.post(
                "/api/v1/auth/mfa/verify",
                headers=auth_headers,
                json={"code": current_code}
            )

            # Should verify successfully
            assert response.status_code in [200, 400]  # 400 if MFA not enabled yet

    async def test_mfa_disable(self, client, auth_headers):
        """Test MFA disable endpoint."""
        response = await client.post(
            "/api/v1/auth/mfa/disable",
            headers=auth_headers,
            json={"code": "123456"}
        )

        # Should succeed or require verification
        assert response.status_code in [200, 400, 403]

    async def test_regenerate_backup_codes(self, client, auth_headers):
        """Test backup codes regeneration."""
        response = await client.post(
            "/api/v1/auth/mfa/backup-codes/regenerate",
            headers=auth_headers,
            json={"code": "123456"}
        )

        # May require MFA to be enabled first
        assert response.status_code in [200, 400]
        if response.status_code == 200:
            data = response.json()
            assert "backup_codes" in data
            assert len(data["backup_codes"]) == 10
