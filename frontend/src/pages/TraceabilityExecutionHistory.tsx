import React, { useState, useEffect } from 'react';
import {
  Box,
  Paper,
  Typography,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Chip,
  IconButton,
  Collapse,
  Alert,
  LinearProgress,
  Tooltip,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
} from '@mui/material';
import {
  KeyboardArrowDown as ExpandMoreIcon,
  KeyboardArrowUp as ExpandLessIcon,
  CheckCircle as SuccessIcon,
  Error as ErrorIcon,
  Warning as WarningIcon,
} from '@mui/icons-material';

interface RuleExecution {
  id: number;
  rule_id: number;
  rule_name: string;
  status: 'success' | 'failed';
  links_created: number;
  executed_at: string;
  execution_log: {
    errors: string[];
    warnings: string[];
    links_created: number;
  };
}

const TraceabilityExecutionHistory: React.FC = () => {
  const [executions, setExecutions] = useState<RuleExecution[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedRow, setExpandedRow] = useState<number | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>('all');

  useEffect(() => {
    fetchExecutions();
  }, []);

  const fetchExecutions = async () => {
    try {
      setLoading(true);
      const response = await fetch('/api/v1/traceability/rules/executions', {
        headers: {
          Authorization: `Bearer ${localStorage.getItem('token')}`,
        },
      });

      if (!response.ok) {
        throw new Error('Failed to fetch executions');
      }

      const data = await response.json();
      setExecutions(data.items || []);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const getStatusIcon = (status: string) => {
    if (status === 'success') {
      return <SuccessIcon color="success" />;
    }
    return <ErrorIcon color="error" />;
  };

  const getStatusColor = (status: string) => {
    return status === 'success' ? 'success' : 'error';
  };

  const filteredExecutions = executions.filter((exec) => {
    if (statusFilter === 'all') return true;
    return exec.status === statusFilter;
  });

  if (loading) {
    return (
      <Box sx={{ width: '100%', mt: 2 }}>
        <LinearProgress />
      </Box>
    );
  }

  if (error) {
    return (
      <Box sx={{ p: 3 }}>
        <Alert severity="error">{error}</Alert>
      </Box>
    );
  }

  return (
    <Box sx={{ p: 3 }}>
      <Box sx={{ mb: 3, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Typography variant="h4">Traceability Execution History</Typography>
        <FormControl sx={{ minWidth: 200 }}>
          <InputLabel>Status</InputLabel>
          <Select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            label="Status"
          >
            <MenuItem value="all">All</MenuItem>
            <MenuItem value="success">Success</MenuItem>
            <MenuItem value="failed">Failed</MenuItem>
          </Select>
        </FormControl>
      </Box>

      <TableContainer component={Paper}>
        <Table>
          <TableHead>
            <TableRow>
              <TableCell width={50} />
              <TableCell>Rule Name</TableCell>
              <TableCell>Status</TableCell>
              <TableCell>Links Created</TableCell>
              <TableCell>Executed At</TableCell>
              <TableCell>Errors</TableCell>
              <TableCell>Warnings</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {filteredExecutions.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} align="center">
                  <Typography variant="body2" color="text.secondary" sx={{ py: 3 }}>
                    No executions found
                  </Typography>
                </TableCell>
              </TableRow>
            ) : (
              filteredExecutions.map((execution) => (
                <React.Fragment key={execution.id}>
                  <TableRow hover>
                    <TableCell>
                      <IconButton
                        size="small"
                        onClick={() =>
                          setExpandedRow(expandedRow === execution.id ? null : execution.id)
                        }
                      >
                        {expandedRow === execution.id ? <ExpandLessIcon /> : <ExpandMoreIcon />}
                      </IconButton>
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2">{execution.rule_name}</Typography>
                    </TableCell>
                    <TableCell>
                      <Chip
                        icon={getStatusIcon(execution.status)}
                        label={execution.status}
                        color={getStatusColor(execution.status)}
                        size="small"
                      />
                    </TableCell>
                    <TableCell>
                      <Chip label={execution.links_created} color="primary" size="small" />
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2" color="text.secondary">
                        {new Date(execution.executed_at).toLocaleString()}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      {execution.execution_log.errors.length > 0 && (
                        <Tooltip title={execution.execution_log.errors.join(', ')}>
                          <Chip
                            icon={<ErrorIcon />}
                            label={execution.execution_log.errors.length}
                            color="error"
                            size="small"
                          />
                        </Tooltip>
                      )}
                    </TableCell>
                    <TableCell>
                      {execution.execution_log.warnings.length > 0 && (
                        <Tooltip title={execution.execution_log.warnings.join(', ')}>
                          <Chip
                            icon={<WarningIcon />}
                            label={execution.execution_log.warnings.length}
                            color="warning"
                            size="small"
                          />
                        </Tooltip>
                      )}
                    </TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell style={{ paddingBottom: 0, paddingTop: 0 }} colSpan={7}>
                      <Collapse in={expandedRow === execution.id} timeout="auto" unmountOnExit>
                        <Box sx={{ p: 2 }}>
                          <Typography variant="h6" gutterBottom>
                            Execution Details
                          </Typography>

                          {execution.execution_log.errors.length > 0 && (
                            <Box sx={{ mb: 2 }}>
                              <Typography variant="subtitle2" color="error" gutterBottom>
                                Errors:
                              </Typography>
                              {execution.execution_log.errors.map((error, idx) => (
                                <Alert key={idx} severity="error" sx={{ mb: 1 }}>
                                  {error}
                                </Alert>
                              ))}
                            </Box>
                          )}

                          {execution.execution_log.warnings.length > 0 && (
                            <Box sx={{ mb: 2 }}>
                              <Typography variant="subtitle2" color="warning.main" gutterBottom>
                                Warnings:
                              </Typography>
                              {execution.execution_log.warnings.map((warning, idx) => (
                                <Alert key={idx} severity="warning" sx={{ mb: 1 }}>
                                  {warning}
                                </Alert>
                              ))}
                            </Box>
                          )}

                          {execution.status === 'success' && (
                            <Alert severity="success">
                              Successfully created {execution.links_created} traceability links
                            </Alert>
                          )}
                        </Box>
                      </Collapse>
                    </TableCell>
                  </TableRow>
                </React.Fragment>
              ))
            )}
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  );
};

export default TraceabilityExecutionHistory;
