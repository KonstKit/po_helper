import React from 'react';
import { Alert, Box, Button, Paper, Stack, Typography } from '@mui/material';

interface ErrorBoundaryProps {
  children: React.ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  errorMessage?: string;
}

class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return {
      hasError: true,
      errorMessage: error.message || 'Unexpected UI error',
    };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo): void {
    if (typeof window !== 'undefined') {
      window.dispatchEvent(
        new CustomEvent('ui-error', {
          detail: {
            message: error.message,
            componentStack: errorInfo.componentStack,
          },
        }),
      );
    }
  }

  private handleReload = (): void => {
    if (typeof window !== 'undefined') {
      window.location.reload();
    }
  };

  render(): React.ReactNode {
    if (!this.state.hasError) {
      return this.props.children;
    }

    return (
      <Box sx={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', p: 3 }}>
        <Paper sx={{ p: 4, maxWidth: 560, width: '100%' }} elevation={3}>
          <Stack spacing={2}>
            <Typography variant="h5">Application error</Typography>
            <Typography variant="body2" color="text.secondary">
              The current screen failed to render. Reload the application to recover.
            </Typography>
            {this.state.errorMessage && (
              <Alert severity="error">{this.state.errorMessage}</Alert>
            )}
            <Box>
              <Button variant="contained" onClick={this.handleReload}>
                Reload application
              </Button>
            </Box>
          </Stack>
        </Paper>
      </Box>
    );
  }
}

export default ErrorBoundary;
