import React, { useState, useEffect } from 'react';
import { Alert, AlertTitle, Snackbar, Button, Box, CircularProgress } from '@mui/material';
import { backendHealthMonitor, BackendHealthStatus } from '../utils/backendHealth';

const BackendStatusAlert: React.FC = () => {
  const [status, setStatus] = useState<BackendHealthStatus | null>(null);
  const [showAlert, setShowAlert] = useState(false);
  const [isRetrying, setIsRetrying] = useState(false);

  useEffect(() => {
    // Listen for backend health changes
    const handleHealthChange = (event: CustomEvent) => {
      const { isHealthy, status: newStatus } = event.detail;
      setStatus(newStatus);
      setShowAlert(!isHealthy);
    };

    // Listen for backend errors from API interceptor
    const handleBackendError = (event: CustomEvent) => {
      const { type, message } = event.detail;
      setStatus({
        isHealthy: false,
        lastChecked: new Date(),
        error: message,
        consecutiveFailures: 1
      });
      setShowAlert(true);
    };

    window.addEventListener('backend-health-change', handleHealthChange as EventListener);
    window.addEventListener('backend-error', handleBackendError as EventListener);

    // Check initial status
    const initialStatus = backendHealthMonitor.getStatus();
    setStatus(initialStatus);
    setShowAlert(!initialStatus.isHealthy);

    return () => {
      window.removeEventListener('backend-health-change', handleHealthChange as EventListener);
      window.removeEventListener('backend-error', handleBackendError as EventListener);
    };
  }, []);

  const handleRetry = async () => {
    setIsRetrying(true);
    const newStatus = await backendHealthMonitor.checkHealth();
    setStatus(newStatus);
    setShowAlert(!newStatus.isHealthy);
    setIsRetrying(false);

    if (newStatus.isHealthy) {
      // Reload page to refresh data
      window.location.reload();
    }
  };

  const handleClose = () => {
    setShowAlert(false);
  };

  if (!status || status.isHealthy) {
    return null;
  }

  return (
    <>
      {/* Persistent top banner for critical backend issues */}
      {showAlert && status.consecutiveFailures >= 3 && (
        <Alert
          severity="error"
          sx={{
            borderRadius: 0,
            position: 'sticky',
            top: 0,
            zIndex: 1200,
            width: '100%'
          }}
        >
          <AlertTitle>Backend Server Unavailable</AlertTitle>
          <Box display="flex" alignItems="center" gap={2}>
            <Box flex={1}>
              The backend server is not responding. Data cannot be loaded or saved.
              {status.error && ` Error: ${status.error}`}
            </Box>
            <Box display="flex" gap={1} alignItems="center">
              {isRetrying && <CircularProgress size={20} />}
              <Button
                color="inherit"
                size="small"
                variant="outlined"
                onClick={handleRetry}
                disabled={isRetrying}
              >
                {isRetrying ? 'Retrying...' : 'Retry Connection'}
              </Button>
            </Box>
          </Box>
        </Alert>
      )}

      {/* Snackbar for transient connection issues */}
      <Snackbar
        open={showAlert && status.consecutiveFailures < 3}
        autoHideDuration={6000}
        onClose={handleClose}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert
          onClose={handleClose}
          severity="warning"
          sx={{ width: '100%' }}
          action={
            <Button color="inherit" size="small" onClick={handleRetry} disabled={isRetrying}>
              {isRetrying ? 'Retrying...' : 'Retry'}
            </Button>
          }
        >
          Connection to backend interrupted. Retrying automatically...
        </Alert>
      </Snackbar>
    </>
  );
};

export default BackendStatusAlert;