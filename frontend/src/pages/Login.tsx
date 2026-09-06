import React, { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Container,
  Paper,
  TextField,
  Button,
  Typography,
  Box,
  Alert,
  Link,
  Divider,
  CircularProgress,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
} from '@mui/material';
import GoogleIcon from '@mui/icons-material/Google';
import { Security as SecurityIcon } from '@mui/icons-material';
import { useDispatch } from 'react-redux';
import type { AppDispatch } from '../store/store';
import { loginStart, loginSuccess, loginFailure } from '../store/authSlice';
import {
  getCurrentUser,
  getOAuth2Providers,
  startGoogleOAuth,
  startMicrosoftOAuth,
  googleOAuthCallback,
  microsoftOAuthCallback,
  verifyMFALogin,
  loginWithPassword,
  OAuth2Providers,
} from '../services/api';
import { getErrorMessage } from '../utils/errorUtils';
import { analytics } from '../services/analytics';
import { waitForCookieClear } from '../utils/logout';

type OAuthProvider = 'google' | 'microsoft';

const isOAuthProvider = (value: string): value is OAuthProvider =>
  value === 'google' || value === 'microsoft';

// Microsoft icon SVG component
const MicrosoftIcon = () => (
  <svg width="20" height="20" viewBox="0 0 21 21" fill="none" xmlns="http://www.w3.org/2000/svg">
    <rect x="1" y="1" width="9" height="9" fill="#F25022"/>
    <rect x="11" y="1" width="9" height="9" fill="#7FBA00"/>
    <rect x="1" y="11" width="9" height="9" fill="#00A4EF"/>
    <rect x="11" y="11" width="9" height="9" fill="#FFB900"/>
  </svg>
);

const Login = () => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');

  // OAuth2 state
  const [oauthProviders, setOauthProviders] = useState<OAuth2Providers | null>(null);
  const [oauthLoading, setOauthLoading] = useState<'google' | 'microsoft' | null>(null);
  const [searchParams] = useSearchParams();

  // MFA state
  const [mfaRequired, setMfaRequired] = useState(false);
  const [mfaTempToken, setMfaTempToken] = useState('');
  const [mfaCode, setMfaCode] = useState('');
  const [mfaLoading, setMfaLoading] = useState(false);

  const navigate = useNavigate();
  const dispatch = useDispatch<AppDispatch>();

  // Load available OAuth providers on mount
  useEffect(() => {
    const loadProviders = async () => {
      try {
        const providers = await getOAuth2Providers();
        setOauthProviders(providers);
      } catch {
        // OAuth not available - continue with password login only
        setOauthProviders({ google: false, microsoft: false });
      }
    };
    loadProviders();
  }, []);

  // Handle OAuth callback (code in URL params)
  useEffect(() => {
    const handleOAuthCallback = async () => {
      const code = searchParams.get('code');
      const state = searchParams.get('state');
      const providerRaw = searchParams.get('oauth_provider') || sessionStorage.getItem('oauth_provider');

      if (!code || !state || !providerRaw) return;
      if (!isOAuthProvider(providerRaw)) {
        setError('Unknown OAuth provider');
        return;
      }
      const provider = providerRaw;

      // Clear stored provider
      sessionStorage.removeItem('oauth_provider');

      setError('');
      dispatch(loginStart());
      setOauthLoading(provider);

      try {
        if (provider === 'google') {
          analytics.bumpAuthGeneration();
          await googleOAuthCallback(code, state);
        } else if (provider === 'microsoft') {
          analytics.bumpAuthGeneration();
          await microsoftOAuthCallback(code, state);
        } else {
          throw new Error('Unknown OAuth provider');
        }

        // The backend set the httpOnly auth cookie on the callback
        // response (JWT storage migration M2); nothing stored locally.
        const profile = await getCurrentUser();
        dispatch(loginSuccess({ user: profile }));
        navigate('/');
      } catch (err: unknown) {
        localStorage.removeItem('token'); // legacy key hygiene
        dispatch(loginFailure());
        setError(getErrorMessage(err, 'OAuth login failed'));
      } finally {
        setOauthLoading(null);
        // Clear URL params
        window.history.replaceState({}, document.title, window.location.pathname);
      }
    };

    handleOAuthCallback();
  }, [searchParams, dispatch, navigate]);

  // Initiate OAuth flow
  const handleOAuthLogin = async (provider: 'google' | 'microsoft') => {
    setError('');
    setOauthLoading(provider);

    try {
      // Store provider for callback handling
      sessionStorage.setItem('oauth_provider', provider);

      let authData;
      if (provider === 'google') {
        authData = await startGoogleOAuth();
      } else {
        authData = await startMicrosoftOAuth();
      }

      // Store state for CSRF protection
      sessionStorage.setItem('oauth_state', authData.state);

      // Redirect to OAuth provider
      window.location.href = authData.authorization_url;
    } catch (err: unknown) {
      setOauthLoading(null);
      sessionStorage.removeItem('oauth_provider');
      setError(getErrorMessage(err, `${provider} login not available`));
    }
  };

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    dispatch(loginStart());

    try {
      // Serialize against an in-flight logout cookie-clear (M2).
      const pendingClear = waitForCookieClear();
      if (pendingClear) await pendingClear;
      analytics.bumpAuthGeneration();
      const response = await loginWithPassword({ username: email, password });

      // Check if MFA is required
      if (response.mfa_required && response.temp_token) {
        setMfaTempToken(response.temp_token);
        setMfaRequired(true);
        dispatch(loginFailure()); // Reset loading state
        return;
      }

      // The login response set the httpOnly auth cookie (dual mode keeps
      // the body token for pre-M2 clients, but we do not store it).
      const profile = await getCurrentUser();

      dispatch(loginSuccess({
        user: profile,
      }));

      navigate('/');
    } catch (err: unknown) {
      localStorage.removeItem('token'); // legacy key hygiene
      dispatch(loginFailure());
      setError(getErrorMessage(err, 'Login failed'));
    }
  };

  // Handle MFA verification
  const handleMFAVerify = async () => {
    if (!mfaCode || mfaCode.length < 6) {
      setError('Please enter a valid 6-digit code');
      return;
    }

    setError('');
    setMfaLoading(true);

    try {
      analytics.bumpAuthGeneration();
      await verifyMFALogin(mfaCode, mfaTempToken);
      // The verify response set the httpOnly auth cookie (M2).
      const profile = await getCurrentUser();

      dispatch(loginSuccess({
        user: profile,
      }));

      setMfaRequired(false);
      setMfaCode('');
      setMfaTempToken('');
      navigate('/');
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Invalid verification code'));
    } finally {
      setMfaLoading(false);
    }
  };

  // Cancel MFA and return to login
  const handleMFACancel = () => {
    setMfaRequired(false);
    setMfaCode('');
    setMfaTempToken('');
    setError('');
  };

  return (
    <Container component="main" maxWidth="xs">
      <Box
        sx={{
          marginTop: 8,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
        }}
      >
        <Paper elevation={3} sx={{ padding: 4, width: '100%' }}>
          <Typography component="h1" variant="h4" align="center" gutterBottom>
            PO Helper
          </Typography>
          <Typography component="h2" variant="h6" align="center" color="text.secondary">
            Sign in to continue
          </Typography>
          <Box component="form" onSubmit={handleLogin} sx={{ mt: 3 }}>
            <TextField
              margin="normal"
              required
              fullWidth
              label="Email Address"
              type="email"
              autoComplete="email"
              autoFocus
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <TextField
              margin="normal"
              required
              fullWidth
              label="Password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            {error && (
              <Alert severity="error" sx={{ mt: 2 }}>
                {error}
              </Alert>
            )}
            <Button
              type="submit"
              fullWidth
              variant="contained"
              sx={{ mt: 3, mb: 2 }}
            >
              Sign In
            </Button>
            {/* Divider only when an alternative (SSO) sign-in method follows */}
            {(oauthProviders?.google || oauthProviders?.microsoft) && (
              <Divider sx={{ my: 2 }} />
            )}

            {/* OAuth2 SSO Buttons */}
            {oauthProviders?.google && (
              <Button
                fullWidth
                variant="outlined"
                startIcon={oauthLoading === 'google' ? <CircularProgress size={20} /> : <GoogleIcon />}
                onClick={() => handleOAuthLogin('google')}
                disabled={oauthLoading !== null}
                sx={{ mb: 1 }}
              >
                {oauthLoading === 'google' ? 'Signing in...' : 'Continue with Google'}
              </Button>
            )}

            {oauthProviders?.microsoft && (
              <Button
                fullWidth
                variant="outlined"
                startIcon={oauthLoading === 'microsoft' ? <CircularProgress size={20} /> : <MicrosoftIcon />}
                onClick={() => handleOAuthLogin('microsoft')}
                disabled={oauthLoading !== null}
                sx={{ mb: 1 }}
              >
                {oauthLoading === 'microsoft' ? 'Signing in...' : 'Continue with Microsoft'}
              </Button>
            )}

            {(oauthProviders?.google || oauthProviders?.microsoft) && (
              <Divider sx={{ my: 2 }} />
            )}
            <Alert severity="info" sx={{ mt: 2 }}>
              Configure Jira and Confluence after sign-in from Settings or onboarding.
            </Alert>
            <Box mt={2} textAlign="center">
              <Link href="#" variant="body2">
                Forgot password?
              </Link>
            </Box>
          </Box>
        </Paper>
      </Box>

      {/* MFA Verification Dialog */}
      <Dialog open={mfaRequired} onClose={handleMFACancel} maxWidth="xs" fullWidth>
        <DialogTitle>
          <Box display="flex" alignItems="center" gap={1}>
            <SecurityIcon color="primary" />
            <Typography variant="h6">Two-Factor Authentication</Typography>
          </Box>
        </DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" paragraph>
            Enter the 6-digit code from your authenticator app to complete sign in.
          </Typography>
          <TextField
            autoFocus
            fullWidth
            label="Verification Code"
            placeholder="000000"
            value={mfaCode}
            onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
            inputProps={{ maxLength: 6, pattern: '[0-9]*', inputMode: 'numeric' }}
            sx={{ mt: 1 }}
          />
          <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
            You can also use a backup code if you don&apos;t have access to your authenticator.
          </Typography>
          {error && (
            <Alert severity="error" sx={{ mt: 2 }}>
              {error}
            </Alert>
          )}
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={handleMFACancel} disabled={mfaLoading}>
            Cancel
          </Button>
          <Button
            variant="contained"
            onClick={handleMFAVerify}
            disabled={mfaLoading || mfaCode.length < 6}
          >
            {mfaLoading ? <CircularProgress size={20} /> : 'Verify'}
          </Button>
        </DialogActions>
      </Dialog>
    </Container>
  );
};

export default Login;

