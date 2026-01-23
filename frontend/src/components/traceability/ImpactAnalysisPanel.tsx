import React, { useState, useCallback } from 'react';
import {
  Box,
  Paper,
  Typography,
  CircularProgress,
  Alert,
  Chip,
  Button,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  Collapse,
  LinearProgress,
  Stack,
  Divider,
  Card,
  CardContent,
} from '@mui/material';
import type { SelectChangeEvent } from '@mui/material/Select';
import {
  Warning,
  Error as ErrorIcon,
  CheckCircle,
  ExpandLess,
  ExpandMore,
  TrendingUp,
  BugReport,
  Code,
  Description,
  Link as LinkIcon,
} from '@mui/icons-material';
import { getImpactAnalysis, ImpactAnalysisResponse, ImpactedArtifact } from '../../services/api';
import { getErrorMessage } from '../../utils/errorUtils';

interface ImpactAnalysisPanelProps {
  artifactId: number;
  artifactTitle?: string;
  onArtifactClick?: (artifactId: number) => void;
}

const RISK_COLORS: Record<string, string> = {
  low: '#4CAF50',
  medium: '#FF9800',
  high: '#F44336',
  critical: '#9C27B0',
};

const RISK_ICONS: Record<string, React.ReactNode> = {
  low: <CheckCircle color="success" />,
  medium: <Warning color="warning" />,
  high: <ErrorIcon color="error" />,
  critical: <ErrorIcon sx={{ color: '#9C27B0' }} />,
};

const TYPE_ICONS: Record<string, React.ReactNode> = {
  requirement: <Description />,
  jira_issue: <BugReport />,
  commit: <Code />,
  pr: <Code />,
  confluence_page: <Description />,
  test_case: <CheckCircle />,
  default: <LinkIcon />,
};

const ImpactAnalysisPanel: React.FC<ImpactAnalysisPanelProps> = ({
  artifactId,
  artifactTitle,
  onArtifactClick,
}) => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<ImpactAnalysisResponse | null>(null);
  const [changeType, setChangeType] = useState<'modify' | 'delete' | 'status_change'>('modify');
  const [directExpanded, setDirectExpanded] = useState(true);
  const [indirectExpanded, setIndirectExpanded] = useState(true);

  const handleChangeType = (event: SelectChangeEvent) => {
    const value = event.target.value;
    if (value === 'modify' || value === 'delete' || value === 'status_change') {
      setChangeType(value);
    }
  };

  const runAnalysis = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await getImpactAnalysis(artifactId, { changeType });
      setData(response);
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to run impact analysis'));
    } finally {
      setLoading(false);
    }
  }, [artifactId, changeType]);

  const renderArtifactItem = (artifact: ImpactedArtifact) => (
    <ListItem
      key={artifact.id}
      button
      onClick={() => onArtifactClick?.(artifact.id)}
      sx={{
        bgcolor: artifact.impact_type === 'direct' ? 'error.50' : 'warning.50',
        mb: 0.5,
        borderRadius: 1,
      }}
    >
      <ListItemIcon>
        {TYPE_ICONS[artifact.type] || TYPE_ICONS.default}
      </ListItemIcon>
      <ListItemText
        primary={artifact.title || `Artifact #${artifact.id}`}
        secondary={
          <Stack direction="row" spacing={1} mt={0.5}>
            <Chip size="small" label={artifact.type} />
            <Chip size="small" label={`Distance: ${artifact.distance}`} variant="outlined" />
            {artifact.status && (
              <Chip size="small" label={artifact.status} variant="outlined" />
            )}
          </Stack>
        }
      />
    </ListItem>
  );

  return (
    <Paper sx={{ p: 2 }}>
      <Typography variant="h6" gutterBottom>
        Impact Analysis
      </Typography>
      {artifactTitle && (
        <Typography variant="body2" color="text.secondary" gutterBottom>
          Analyzing changes to: <strong>{artifactTitle}</strong>
        </Typography>
      )}

      <Stack direction="row" spacing={2} alignItems="center" mb={2}>
        <FormControl size="small" sx={{ minWidth: 150 }}>
          <InputLabel>Change Type</InputLabel>
            <Select
              value={changeType}
              label="Change Type"
              onChange={handleChangeType}
            >
            <MenuItem value="modify">Modify</MenuItem>
            <MenuItem value="delete">Delete</MenuItem>
            <MenuItem value="status_change">Status Change</MenuItem>
          </Select>
        </FormControl>

        <Button
          variant="contained"
          onClick={runAnalysis}
          disabled={loading}
          startIcon={loading ? <CircularProgress size={16} /> : <TrendingUp />}
        >
          {loading ? 'Analyzing...' : 'Run Analysis'}
        </Button>
      </Stack>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      {data && (
        <Box>
          {/* Risk Score Card */}
          <Card
            sx={{
              mb: 2,
              bgcolor: `${RISK_COLORS[data.risk_level]}15`,
              borderLeft: `4px solid ${RISK_COLORS[data.risk_level]}`,
            }}
          >
            <CardContent>
              <Stack direction="row" alignItems="center" spacing={2}>
                {RISK_ICONS[data.risk_level]}
                <Box flex={1}>
                  <Typography variant="h6">
                    Risk Level: {data.risk_level.toUpperCase()}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    Score: {Math.round(data.risk_score * 100)}%
                  </Typography>
                </Box>
                <Box sx={{ width: 150 }}>
                  <LinearProgress
                    variant="determinate"
                    value={data.risk_score * 100}
                    sx={{
                      height: 10,
                      borderRadius: 1,
                      bgcolor: '#e0e0e0',
                      '& .MuiLinearProgress-bar': {
                        bgcolor: RISK_COLORS[data.risk_level],
                      },
                    }}
                  />
                </Box>
              </Stack>
            </CardContent>
          </Card>

          {/* Stats */}
          <Stack direction="row" spacing={2} mb={2}>
            <Chip
              label={`${data.stats.total_affected} affected`}
              color="error"
              variant="outlined"
            />
            <Chip
              label={`${data.stats.direct_count} direct`}
              color="warning"
            />
            <Chip
              label={`${data.stats.indirect_count} indirect`}
              variant="outlined"
            />
          </Stack>

          {/* Affected Types Breakdown */}
          {Object.keys(data.stats.affected_types).length > 0 && (
            <Box mb={2}>
              <Typography variant="subtitle2" gutterBottom>
                Affected by Type:
              </Typography>
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                {Object.entries(data.stats.affected_types).map(([type, count]) => (
                  <Chip
                    key={type}
                    size="small"
                    label={`${type}: ${count}`}
                    variant="outlined"
                  />
                ))}
              </Stack>
            </Box>
          )}

          {/* Recommendations */}
          {data.recommendations.length > 0 && (
            <Alert severity="info" sx={{ mb: 2 }}>
              <Typography variant="subtitle2" gutterBottom>
                Recommendations:
              </Typography>
              <ul style={{ margin: 0, paddingLeft: 20 }}>
                {data.recommendations.map((rec, idx) => (
                  <li key={idx}>
                    <Typography variant="body2">{rec}</Typography>
                  </li>
                ))}
              </ul>
            </Alert>
          )}

          <Divider sx={{ my: 2 }} />

          {/* Directly Affected */}
          <Box>
            <ListItem button onClick={() => setDirectExpanded(!directExpanded)}>
              <ListItemIcon>
                <ErrorIcon color="error" />
              </ListItemIcon>
              <ListItemText
                primary={`Directly Affected (${data.directly_affected.length})`}
                secondary="Artifacts with immediate dependency"
              />
              {directExpanded ? <ExpandLess /> : <ExpandMore />}
            </ListItem>
            <Collapse in={directExpanded}>
              <List dense sx={{ pl: 2 }}>
                {data.directly_affected.length === 0 ? (
                  <Typography variant="body2" color="text.secondary" sx={{ pl: 2 }}>
                    No directly affected artifacts
                  </Typography>
                ) : (
                  data.directly_affected.map(renderArtifactItem)
                )}
              </List>
            </Collapse>
          </Box>

          {/* Indirectly Affected */}
          <Box>
            <ListItem button onClick={() => setIndirectExpanded(!indirectExpanded)}>
              <ListItemIcon>
                <Warning color="warning" />
              </ListItemIcon>
              <ListItemText
                primary={`Indirectly Affected (${data.indirectly_affected.length})`}
                secondary="Artifacts affected through chain"
              />
              {indirectExpanded ? <ExpandLess /> : <ExpandMore />}
            </ListItem>
            <Collapse in={indirectExpanded}>
              <List dense sx={{ pl: 2 }}>
                {data.indirectly_affected.length === 0 ? (
                  <Typography variant="body2" color="text.secondary" sx={{ pl: 2 }}>
                    No indirectly affected artifacts
                  </Typography>
                ) : (
                  data.indirectly_affected.map(renderArtifactItem)
                )}
              </List>
            </Collapse>
          </Box>
        </Box>
      )}

      {!data && !loading && !error && (
        <Typography variant="body2" color="text.secondary" textAlign="center" py={4}>
          Click &quot;Run Analysis&quot; to see the impact of changes to this artifact
        </Typography>
      )}
    </Paper>
  );
};

export default ImpactAnalysisPanel;
