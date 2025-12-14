import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
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
} from '@mui/material';
import { useDispatch } from 'react-redux';
import { loginStart, loginSuccess, loginFailure } from '../store/authSlice';
import api, { getCurrentUser } from '../services/api';

const Login = () => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [isJiraConfig, setIsJiraConfig] = useState(false);
  const [jiraUrl, setJiraUrl] = useState('');
  const [jiraEmail, setJiraEmail] = useState('');
  const [jiraToken, setJiraToken] = useState('');
  
  const navigate = useNavigate();
  const dispatch = useDispatch();

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    dispatch(loginStart());

    try {
      const formData = new URLSearchParams();
      formData.append('username', email);
      formData.append('password', password);

      const response = await api.post('/v1/auth/login', formData, {
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
        },
      });

      const { access_token } = response.data;

      // Persist token immediately for subsequent requests
      localStorage.setItem('token', access_token);
      const profile = await getCurrentUser();

      dispatch(loginSuccess({
        user: profile,
        token: access_token,
      }));

      navigate('/');
    } catch (err: any) {
      localStorage.removeItem('token');
      dispatch(loginFailure());
      setError(err.response?.data?.detail || 'Login failed');
    }
  };

  const handleJiraConnect = async () => {
    try {
      await axios.post('http://localhost:8000/api/v1/jira/connect', {
        base_url: jiraUrl,
        email: jiraEmail,
        api_token: jiraToken,
      });
      
      setIsJiraConfig(false);
      // Show success message
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to connect to Jira');
    }
  };

  if (isJiraConfig) {
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
            <Typography component="h1" variant="h5" align="center">
              Configure Jira Connection
            </Typography>
            <Box component="form" onSubmit={(e) => { e.preventDefault(); handleJiraConnect(); }} sx={{ mt: 1 }}>
              <TextField
                margin="normal"
                required
                fullWidth
                label="Jira URL"
                placeholder="https://company.atlassian.net"
                value={jiraUrl}
                onChange={(e) => setJiraUrl(e.target.value)}
              />
              <TextField
                margin="normal"
                required
                fullWidth
                label="Jira Email"
                type="email"
                value={jiraEmail}
                onChange={(e) => setJiraEmail(e.target.value)}
              />
              <TextField
                margin="normal"
                required
                fullWidth
                label="Jira API Token"
                type="password"
                value={jiraToken}
                onChange={(e) => setJiraToken(e.target.value)}
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
                Connect to Jira
              </Button>
              <Button
                fullWidth
                variant="text"
                onClick={() => setIsJiraConfig(false)}
              >
                Back to Login
              </Button>
            </Box>
          </Paper>
        </Box>
      </Container>
    );
  }

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
            <Divider sx={{ my: 2 }}>OR</Divider>
            <Button
              fullWidth
              variant="outlined"
              onClick={() => setIsJiraConfig(true)}
            >
              Configure Jira Connection
            </Button>
            <Box mt={2} textAlign="center">
              <Link href="#" variant="body2">
                Forgot password?
              </Link>
            </Box>
          </Box>
        </Paper>
      </Box>
    </Container>
  );
};

export default Login;








