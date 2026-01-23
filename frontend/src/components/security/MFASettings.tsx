/**
 * Multi-Factor Authentication (MFA) Settings Component
 *
 * Provides UI for:
 * - Viewing MFA status
 * - Setting up MFA with QR code
 * - Verifying authenticator setup
 * - Disabling MFA
 * - Regenerating backup codes
 */
import React, { useState, useEffect } from 'react';
import {
  Box,
  Typography,
  Button,
  TextField,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Alert,
  CircularProgress,
  Chip,
  Divider,
  Paper,
  List,
  ListItem,
  ListItemText,
  IconButton,
  Tooltip,
  Collapse,
} from '@mui/material';
import {
  Security as SecurityIcon,
  QrCode2 as QrCodeIcon,
  ContentCopy as CopyIcon,
  Visibility as VisibilityIcon,
  VisibilityOff as VisibilityOffIcon,
  CheckCircle as CheckIcon,
  Refresh as RefreshIcon,
} from '@mui/icons-material';
import {
  getMFAStatus,
  initiateMFASetup,
  verifyMFASetup,
  disableMFA,
  regenerateBackupCodes,
  type MFAStatus,
  type MFASetupResponse,
} from '../../services/api';
import { getErrorMessage } from '../../utils/errorUtils';

type SetupStep = 'idle' | 'loading' | 'qr' | 'verify' | 'backup' | 'complete';

interface MFASettingsProps {
  onStatusChange?: (enabled: boolean) => void;
}

const MFASettings: React.FC<MFASettingsProps> = ({ onStatusChange }) => {
  const [status, setStatus] = useState<MFAStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Setup flow state
  const [setupStep, setSetupStep] = useState<SetupStep>('idle');
  const [setupData, setSetupData] = useState<MFASetupResponse | null>(null);
  const [verifyCode, setVerifyCode] = useState('');
  const [showBackupCodes, setShowBackupCodes] = useState(false);
  const [backupCodes, setBackupCodes] = useState<string[]>([]);

  // Disable dialog state
  const [disableDialogOpen, setDisableDialogOpen] = useState(false);
  const [disableCode, setDisableCode] = useState('');
  const [disableLoading, setDisableLoading] = useState(false);

  // Regenerate dialog state
  const [regenerateDialogOpen, setRegenerateDialogOpen] = useState(false);
  const [regenerateCode, setRegenerateCode] = useState('');
  const [regenerateLoading, setRegenerateLoading] = useState(false);

  // Load MFA status on mount
  useEffect(() => {
    loadStatus();
  }, []);

  const loadStatus = async () => {
    try {
      setLoading(true);
      const data = await getMFAStatus();
      setStatus(data);
    } catch {
      setError('Failed to load MFA status');
    } finally {
      setLoading(false);
    }
  };

  const handleStartSetup = async () => {
    try {
      setSetupStep('loading');
      setError(null);
      const data = await initiateMFASetup();
      setSetupData(data);
      setBackupCodes(data.backup_codes);
      setSetupStep('qr');
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to start MFA setup'));
      setSetupStep('idle');
    }
  };

  const handleVerifySetup = async () => {
    if (!verifyCode || verifyCode.length < 6) {
      setError('Please enter a valid 6-digit code');
      return;
    }

    try {
      setSetupStep('loading');
      setError(null);
      await verifyMFASetup(verifyCode);
      setSetupStep('backup');
      setSuccess('MFA has been enabled successfully!');
      await loadStatus();
      onStatusChange?.(true);
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Invalid verification code'));
      setSetupStep('verify');
    }
  };

  const handleDisableMFA = async () => {
    if (!disableCode) {
      setError('Please enter your verification code');
      return;
    }

    try {
      setDisableLoading(true);
      setError(null);
      await disableMFA(disableCode);
      setSuccess('MFA has been disabled');
      setDisableDialogOpen(false);
      setDisableCode('');
      await loadStatus();
      onStatusChange?.(false);
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to disable MFA'));
    } finally {
      setDisableLoading(false);
    }
  };

  const handleRegenerateBackupCodes = async () => {
    if (!regenerateCode) {
      setError('Please enter your verification code');
      return;
    }

    try {
      setRegenerateLoading(true);
      setError(null);
      const result = await regenerateBackupCodes(regenerateCode);
      setBackupCodes(result.backup_codes);
      setShowBackupCodes(true);
      setSuccess('New backup codes generated. Please save them securely.');
      setRegenerateDialogOpen(false);
      setRegenerateCode('');
      await loadStatus();
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to regenerate backup codes'));
    } finally {
      setRegenerateLoading(false);
    }
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setSuccess('Copied to clipboard');
  };

  const copyAllBackupCodes = () => {
    const allCodes = backupCodes.join('\n');
    navigator.clipboard.writeText(allCodes);
    setSuccess('All backup codes copied to clipboard');
  };

  const resetSetup = () => {
    setSetupStep('idle');
    setSetupData(null);
    setVerifyCode('');
    setShowBackupCodes(false);
  };

  if (loading) {
    return (
      <Box display="flex" justifyContent="center" p={4}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box>
      {/* Status Header */}
      <Box display="flex" alignItems="center" gap={2} mb={3}>
        <SecurityIcon color={status?.mfa_enabled ? 'success' : 'action'} />
        <Box flex={1}>
          <Typography variant="h6">Two-Factor Authentication</Typography>
          <Typography variant="body2" color="text.secondary">
            Add an extra layer of security to your account
          </Typography>
        </Box>
        <Chip
          label={status?.mfa_enabled ? 'Enabled' : 'Disabled'}
          color={status?.mfa_enabled ? 'success' : 'default'}
          icon={status?.mfa_enabled ? <CheckIcon /> : undefined}
        />
      </Box>

      {/* Alerts */}
      <Collapse in={!!error}>
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      </Collapse>
      <Collapse in={!!success}>
        <Alert severity="success" sx={{ mb: 2 }} onClose={() => setSuccess(null)}>
          {success}
        </Alert>
      </Collapse>

      {/* MFA Not Enabled - Show Setup */}
      {!status?.mfa_enabled && setupStep === 'idle' && (
        <Paper variant="outlined" sx={{ p: 3 }}>
          <Typography variant="body1" paragraph>
            Protect your account with time-based one-time passwords (TOTP).
            You&apos;ll need an authenticator app like:
          </Typography>
          <List dense>
            <ListItem><ListItemText primary="Google Authenticator" /></ListItem>
            <ListItem><ListItemText primary="Microsoft Authenticator" /></ListItem>
            <ListItem><ListItemText primary="Authy" /></ListItem>
            <ListItem><ListItemText primary="1Password" /></ListItem>
          </List>
          <Button
            variant="contained"
            startIcon={<QrCodeIcon />}
            onClick={handleStartSetup}
            sx={{ mt: 2 }}
          >
            Set Up Two-Factor Authentication
          </Button>
        </Paper>
      )}

      {/* Setup Loading */}
      {setupStep === 'loading' && (
        <Box display="flex" justifyContent="center" p={4}>
          <CircularProgress />
        </Box>
      )}

      {/* QR Code Step */}
      {setupStep === 'qr' && setupData && (
        <Paper variant="outlined" sx={{ p: 3 }}>
          <Typography variant="h6" gutterBottom>
            Step 1: Scan QR Code
          </Typography>
          <Typography variant="body2" color="text.secondary" paragraph>
            Open your authenticator app and scan this QR code:
          </Typography>

          <Box display="flex" justifyContent="center" my={3}>
            <img
              src={setupData.qr_code}
              alt="MFA QR Code"
              style={{ maxWidth: 200, border: '1px solid #ccc', borderRadius: 8 }}
            />
          </Box>

          <Typography variant="body2" color="text.secondary" paragraph>
            Can&apos;t scan the code? Enter this key manually:
          </Typography>
          <Box
            sx={{
              bgcolor: 'grey.100',
              p: 2,
              borderRadius: 1,
              display: 'flex',
              alignItems: 'center',
              gap: 1,
            }}
          >
            <code style={{ flex: 1, wordBreak: 'break-all' }}>{setupData.secret}</code>
            <Tooltip title="Copy secret">
              <IconButton size="small" onClick={() => copyToClipboard(setupData.secret)}>
                <CopyIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </Box>

          <Box display="flex" justifyContent="flex-end" gap={2} mt={3}>
            <Button onClick={resetSetup}>Cancel</Button>
            <Button variant="contained" onClick={() => setSetupStep('verify')}>
              Next
            </Button>
          </Box>
        </Paper>
      )}

      {/* Verify Step */}
      {setupStep === 'verify' && (
        <Paper variant="outlined" sx={{ p: 3 }}>
          <Typography variant="h6" gutterBottom>
            Step 2: Verify Setup
          </Typography>
          <Typography variant="body2" color="text.secondary" paragraph>
            Enter the 6-digit code from your authenticator app to verify the setup:
          </Typography>

          <TextField
            label="Verification Code"
            value={verifyCode}
            onChange={(e) => setVerifyCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
            fullWidth
            inputProps={{ maxLength: 6, pattern: '[0-9]*' }}
            placeholder="000000"
            sx={{ my: 2 }}
          />

          <Box display="flex" justifyContent="flex-end" gap={2}>
            <Button onClick={() => setSetupStep('qr')}>Back</Button>
            <Button
              variant="contained"
              onClick={handleVerifySetup}
              disabled={verifyCode.length !== 6}
            >
              Verify & Enable
            </Button>
          </Box>
        </Paper>
      )}

      {/* Backup Codes Step */}
      {setupStep === 'backup' && (
        <Paper variant="outlined" sx={{ p: 3 }}>
          <Typography variant="h6" gutterBottom>
            Step 3: Save Backup Codes
          </Typography>
          <Alert severity="warning" sx={{ mb: 2 }}>
            Save these backup codes in a secure location. Each code can only be used once
            and will help you access your account if you lose your phone.
          </Alert>

          <Box
            sx={{
              bgcolor: 'grey.100',
              p: 2,
              borderRadius: 1,
              fontFamily: 'monospace',
            }}
          >
            {backupCodes.map((code, idx) => (
              <Box key={idx} display="flex" justifyContent="space-between" py={0.5}>
                <Typography fontFamily="monospace">{code}</Typography>
              </Box>
            ))}
          </Box>

          <Box display="flex" justifyContent="space-between" mt={2}>
            <Button startIcon={<CopyIcon />} onClick={copyAllBackupCodes}>
              Copy All Codes
            </Button>
            <Button variant="contained" onClick={resetSetup}>
              Done
            </Button>
          </Box>
        </Paper>
      )}

      {/* MFA Enabled - Show Status and Actions */}
      {status?.mfa_enabled && setupStep === 'idle' && (
        <Box>
          <Paper variant="outlined" sx={{ p: 3, mb: 2 }}>
            <Box display="flex" alignItems="center" gap={2}>
              <CheckIcon color="success" />
              <Box flex={1}>
                <Typography variant="body1">
                  Two-factor authentication is active
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  {status.remaining_backup_codes} backup codes remaining
                </Typography>
              </Box>
            </Box>
          </Paper>

          {/* Show backup codes if available */}
          {backupCodes.length > 0 && (
            <Paper variant="outlined" sx={{ p: 3, mb: 2 }}>
              <Box display="flex" alignItems="center" justifyContent="space-between" mb={2}>
                <Typography variant="subtitle1">Backup Codes</Typography>
                <IconButton onClick={() => setShowBackupCodes(!showBackupCodes)}>
                  {showBackupCodes ? <VisibilityOffIcon /> : <VisibilityIcon />}
                </IconButton>
              </Box>
              <Collapse in={showBackupCodes}>
                <Box
                  sx={{
                    bgcolor: 'grey.100',
                    p: 2,
                    borderRadius: 1,
                    fontFamily: 'monospace',
                  }}
                >
                  {backupCodes.map((code, idx) => (
                    <Typography key={idx} fontFamily="monospace" py={0.25}>
                      {code}
                    </Typography>
                  ))}
                </Box>
                <Button
                  size="small"
                  startIcon={<CopyIcon />}
                  onClick={copyAllBackupCodes}
                  sx={{ mt: 1 }}
                >
                  Copy All
                </Button>
              </Collapse>
            </Paper>
          )}

          {/* Warning if low on backup codes */}
          {status.remaining_backup_codes <= 3 && (
            <Alert severity="warning" sx={{ mb: 2 }}>
              You have only {status.remaining_backup_codes} backup codes left.
              Consider regenerating them.
            </Alert>
          )}

          <Divider sx={{ my: 2 }} />

          <Box display="flex" gap={2}>
            <Button
              variant="outlined"
              startIcon={<RefreshIcon />}
              onClick={() => setRegenerateDialogOpen(true)}
            >
              Regenerate Backup Codes
            </Button>
            <Button
              variant="outlined"
              color="error"
              onClick={() => setDisableDialogOpen(true)}
            >
              Disable 2FA
            </Button>
          </Box>
        </Box>
      )}

      {/* Disable MFA Dialog */}
      <Dialog open={disableDialogOpen} onClose={() => setDisableDialogOpen(false)}>
        <DialogTitle>Disable Two-Factor Authentication</DialogTitle>
        <DialogContent>
          <Typography paragraph>
            Enter your authenticator code or a backup code to confirm:
          </Typography>
          <TextField
            label="Verification Code"
            value={disableCode}
            onChange={(e) => setDisableCode(e.target.value)}
            fullWidth
            autoFocus
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDisableDialogOpen(false)}>Cancel</Button>
          <Button
            color="error"
            onClick={handleDisableMFA}
            disabled={disableLoading || !disableCode}
          >
            {disableLoading ? <CircularProgress size={20} /> : 'Disable'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Regenerate Backup Codes Dialog */}
      <Dialog open={regenerateDialogOpen} onClose={() => setRegenerateDialogOpen(false)}>
        <DialogTitle>Regenerate Backup Codes</DialogTitle>
        <DialogContent>
          <Alert severity="warning" sx={{ mb: 2 }}>
            This will invalidate all existing backup codes.
          </Alert>
          <Typography paragraph>
            Enter your authenticator code to confirm:
          </Typography>
          <TextField
            label="Authenticator Code"
            value={regenerateCode}
            onChange={(e) => setRegenerateCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
            fullWidth
            autoFocus
            inputProps={{ maxLength: 6 }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRegenerateDialogOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={handleRegenerateBackupCodes}
            disabled={regenerateLoading || regenerateCode.length !== 6}
          >
            {regenerateLoading ? <CircularProgress size={20} /> : 'Regenerate'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default MFASettings;
