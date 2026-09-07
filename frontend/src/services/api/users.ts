/**
 * User APIs - Current user operations and authentication.
 */
import api, { CACHE_TTL } from './client';
import { storage } from '../../utils/storage';
import { deduplicateRequest } from '../../utils/apiOptimization';
import type { User } from './types';

export const getCurrentUser = async (): Promise<User> => {
  const cacheKey = 'current_user';

  const cached = storage.get<User>(cacheKey);
  if (cached !== null) {
    return cached;
  }

  return deduplicateRequest(cacheKey, async () => {
    const { data } = await api.get("/v1/users/me");
    storage.set(cacheKey, data, { ttl: CACHE_TTL * 5 }); // Cache for 5 minutes
    return data;
  });
};

export const updateCurrentUser = async (
  payload: Partial<Pick<User, "username" | "full_name">>,
): Promise<User> => {
  const { data } = await api.patch("/v1/users/me", payload);
  // Invalidate cache
  storage.remove('current_user');
  return data;
};

export const changePassword = async (payload: {
  current_password: string;
  new_password: string;
}): Promise<{ message: string }> => {
  const { data } = await api.post("/v1/users/me/password", payload);
  return data;
};

// =============================================================================
// Password Login
// =============================================================================

export interface LoginResponse {
  /** M4: absent by default (cookie-only session); present only in dual mode. */
  access_token?: string;
  token_type?: string;
  mfa_required?: boolean;
  temp_token?: string;
}

export const loginWithPassword = async (payload: {
  username: string;
  password: string;
}): Promise<LoginResponse> => {
  const formData = new URLSearchParams();
  formData.append('username', payload.username);
  formData.append('password', payload.password);

  const { data } = await api.post('/v1/auth/login', formData, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  });
  return data as LoginResponse;
};

// =============================================================================
// OAuth2 SSO
// =============================================================================

export interface OAuth2Providers {
  google: boolean;
  microsoft: boolean;
}

export interface OAuth2AuthURL {
  authorization_url: string;
  state: string;
}

export interface OAuth2Token {
  /** M4: absent (cookie-only session) unless dual mode is enabled. */
  access_token?: string;
  token_type: string;
}

/**
 * Get available OAuth2 providers and their configuration status.
 */
export const getOAuth2Providers = async (): Promise<OAuth2Providers> => {
  const { data } = await api.get<OAuth2Providers>("/v1/auth/oauth2/providers");
  return data;
};

/**
 * Initiate Google OAuth2 authentication flow.
 * Returns authorization URL for frontend to redirect user.
 */
export const startGoogleOAuth = async (redirectUri?: string): Promise<OAuth2AuthURL> => {
  const params = redirectUri ? { redirect_uri: redirectUri } : {};
  const { data } = await api.get<OAuth2AuthURL>("/v1/auth/oauth2/google", { params });
  return data;
};

/**
 * Initiate Microsoft OAuth2 authentication flow.
 * Returns authorization URL for frontend to redirect user.
 */
export const startMicrosoftOAuth = async (redirectUri?: string): Promise<OAuth2AuthURL> => {
  const params = redirectUri ? { redirect_uri: redirectUri } : {};
  const { data } = await api.get<OAuth2AuthURL>("/v1/auth/oauth2/microsoft", { params });
  return data;
};

/**
 * Exchange Google OAuth2 callback code for token.
 */
export const googleOAuthCallback = async (code: string, state: string): Promise<OAuth2Token> => {
  const { data } = await api.get<OAuth2Token>("/v1/auth/oauth2/google/callback", {
    params: { code, state },
  });
  return data;
};

/**
 * Exchange Microsoft OAuth2 callback code for token.
 */
export const microsoftOAuthCallback = async (code: string, state: string): Promise<OAuth2Token> => {
  const { data } = await api.get<OAuth2Token>("/v1/auth/oauth2/microsoft/callback", {
    params: { code, state },
  });
  return data;
};


// =============================================================================
// Multi-Factor Authentication (MFA)
// =============================================================================

export interface MFAStatus {
  mfa_enabled: boolean;
  mfa_configured: boolean;
  remaining_backup_codes: number;
}

export interface MFASetupResponse {
  secret: string;
  qr_code: string;
  provisioning_uri: string;
  backup_codes: string[];
}

export interface MFAVerifyResponse {
  message: string;
  mfa_enabled: boolean;
  remaining_backup_codes?: number;
}

export interface MFALoginResponse {
  mfa_required: boolean;
  temp_token: string;
  message: string;
}

/**
 * Get current MFA status for the authenticated user.
 */
export const getMFAStatus = async (): Promise<MFAStatus> => {
  const { data } = await api.get<MFAStatus>("/v1/auth/mfa/status");
  return data;
};

/**
 * Initialize MFA setup for the current user.
 * Returns QR code and backup codes. User must verify with TOTP code to enable.
 */
export const initiateMFASetup = async (): Promise<MFASetupResponse> => {
  const { data } = await api.post<MFASetupResponse>("/v1/auth/mfa/setup");
  return data;
};

/**
 * Verify MFA setup with TOTP code from authenticator app.
 * This confirms user has correctly configured their app and enables MFA.
 */
export const verifyMFASetup = async (code: string): Promise<MFAVerifyResponse> => {
  const { data } = await api.post<MFAVerifyResponse>("/v1/auth/mfa/verify", { code });
  return data;
};

/**
 * Disable MFA for the current user.
 * Requires verification with TOTP code or backup code.
 */
export const disableMFA = async (code: string): Promise<MFAVerifyResponse> => {
  const { data } = await api.post<MFAVerifyResponse>("/v1/auth/mfa/disable", { code });
  return data;
};

/**
 * Regenerate MFA backup codes.
 * Requires verification with TOTP code. Invalidates all previous codes.
 */
export const regenerateBackupCodes = async (code: string): Promise<{ backup_codes: string[] }> => {
  const { data } = await api.post<{ backup_codes: string[] }>("/v1/auth/mfa/backup-codes/regenerate", { code });
  return data;
};

/**
 * Complete login with MFA verification.
 * Called after initial login returns mfa_required=true.
 */
export const verifyMFALogin = async (code: string, tempToken: string): Promise<OAuth2Token> => {
  const { data } = await api.post<OAuth2Token>("/v1/auth/mfa/verify-login", {
    code,
    temp_token: tempToken,
  });
  return data;
};
