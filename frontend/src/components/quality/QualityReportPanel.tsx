/**
 * Quality Report Generation Panel
 *
 * Allows users to generate, preview, and download sprint quality reports
 * in PDF, Excel, or JSON formats.
 */

import React, { useState, useEffect, useCallback } from 'react';
import {
  Box,
  Paper,
  Typography,
  Button,
  Grid,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Checkbox,
  FormControlLabel,
  FormGroup,
  Alert,
  CircularProgress,
  Chip,
  Card,
  CardContent,
  Divider,
  LinearProgress,
  IconButton,
} from '@mui/material';
import type { SelectChangeEvent } from '@mui/material/Select';
import {
  PictureAsPdf as PdfIcon,
  TableChart as ExcelIcon,
  Code as JsonIcon,
  Download as DownloadIcon,
  Visibility as PreviewIcon,
  Refresh as RefreshIcon,
  CheckCircle as CheckIcon,
  Warning as WarningIcon,
  Star as StarIcon,
} from '@mui/icons-material';
import {
  getQualityReportData,
  downloadQualityReport,
  getQualityReportPreviewUrl,
  SprintQualityReport,
  ReportFormat,
  ReportSection,
} from '../../services/api';
import { getErrorMessage } from '../../utils/errorUtils';

interface QualityReportPanelProps {
  projectId?: number;
  sprintId?: number;
}

const SECTION_LABELS: Record<ReportSection, string> = {
  executive_summary: 'Executive Summary',
  quality_metrics: 'Quality Metrics',
  test_coverage: 'Test Coverage',
  flaky_tests: 'Flaky Tests',
  escaped_defects: 'Escaped Defects',
  pr_quality: 'PR Quality Gates',
  component_health: 'Component Health',
  trends: 'Trends',
  recommendations: 'Recommendations',
};

const REPORT_SECTIONS: ReportSection[] = [
  'executive_summary',
  'quality_metrics',
  'test_coverage',
  'flaky_tests',
  'escaped_defects',
  'pr_quality',
  'component_health',
  'trends',
  'recommendations',
];

const GRADE_COLORS: Record<string, string> = {
  A: '#2ecc71',
  B: '#3498db',
  C: '#f1c40f',
  D: '#e67e22',
  F: '#e74c3c',
};

const QualityReportPanel: React.FC<QualityReportPanelProps> = ({
  projectId,
  sprintId,
}) => {
  const [reportData, setReportData] = useState<SprintQualityReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [format, setFormat] = useState<ReportFormat>('pdf');
  const [selectedSections, setSelectedSections] = useState<ReportSection[]>([
    'executive_summary',
    'quality_metrics',
    'test_coverage',
    'escaped_defects',
    'recommendations',
  ]);

  const handleFormatChange = (event: SelectChangeEvent) => {
    const value = event.target.value;
    if (value === 'pdf' || value === 'excel' || value === 'json' || value === 'csv') {
      setFormat(value);
    }
  };

  const loadReportData = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await getQualityReportData(projectId, sprintId);
      setReportData(data);
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to load report data'));
    } finally {
      setLoading(false);
    }
  }, [projectId, sprintId]);

  useEffect(() => {
    if (projectId) {
      loadReportData();
    }
  }, [projectId, loadReportData]);

  const handleDownload = async () => {
    if (!projectId) return;
    setGenerating(true);
    setError(null);
    try {
      const { url, filename } = await downloadQualityReport(
        projectId,
        format,
        sprintId,
        selectedSections
      );
      // Create download link
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to generate report'));
    } finally {
      setGenerating(false);
    }
  };

  const handlePreview = () => {
    if (!projectId) return;
    const url = getQualityReportPreviewUrl(projectId, format, sprintId);
    window.open(url, '_blank');
  };

  const toggleSection = (section: ReportSection) => {
    setSelectedSections(prev =>
      prev.includes(section)
        ? prev.filter(s => s !== section)
        : [...prev, section]
    );
  };

  if (!projectId) {
    return (
      <Paper sx={{ p: 3, textAlign: 'center' }}>
        <Typography color="text.secondary">
          Select a project to generate quality reports
        </Typography>
      </Paper>
    );
  }

  const gradeColor = reportData ? GRADE_COLORS[reportData.quality_grade] || '#666' : '#666';

  return (
    <Box>
      {/* Report Preview Header */}
      {reportData && (
        <Paper sx={{ p: 3, mb: 3 }}>
          <Box display="flex" justifyContent="space-between" alignItems="flex-start">
            <Box>
              <Typography variant="h5" gutterBottom>
                Quality Report Preview
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {reportData.project_name || `Project #${reportData.project_id}`}
                {reportData.sprint_name && ` • ${reportData.sprint_name}`}
              </Typography>
            </Box>
            <Box display="flex" alignItems="center" gap={2}>
              <Box
                sx={{
                  bgcolor: gradeColor,
                  color: 'white',
                  width: 64,
                  height: 64,
                  borderRadius: 2,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <Typography variant="h4" fontWeight="bold">
                  {reportData.quality_grade}
                </Typography>
              </Box>
              <Box>
                <Typography variant="h6">
                  {reportData.overall_quality_score.toFixed(1)}/100
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  Quality Score
                </Typography>
              </Box>
            </Box>
          </Box>

          <Divider sx={{ my: 2 }} />

          {/* Key Highlights & Concerns */}
          <Grid container spacing={3}>
            <Grid item xs={12} md={6}>
              <Typography variant="subtitle2" color="success.main" gutterBottom>
                <CheckIcon sx={{ fontSize: 16, mr: 0.5, verticalAlign: 'middle' }} />
                Key Highlights
              </Typography>
              {reportData.key_highlights.length > 0 ? (
                reportData.key_highlights.map((h, i) => (
                  <Typography key={i} variant="body2" sx={{ ml: 2, mb: 0.5 }}>
                    + {h}
                  </Typography>
                ))
              ) : (
                <Typography variant="body2" color="text.secondary" sx={{ ml: 2 }}>
                  No highlights available
                </Typography>
              )}
            </Grid>
            <Grid item xs={12} md={6}>
              <Typography variant="subtitle2" color="error.main" gutterBottom>
                <WarningIcon sx={{ fontSize: 16, mr: 0.5, verticalAlign: 'middle' }} />
                Key Concerns
              </Typography>
              {reportData.key_concerns.length > 0 ? (
                reportData.key_concerns.map((c, i) => (
                  <Typography key={i} variant="body2" sx={{ ml: 2, mb: 0.5 }}>
                    ! {c}
                  </Typography>
                ))
              ) : (
                <Typography variant="body2" color="text.secondary" sx={{ ml: 2 }}>
                  No concerns identified
                </Typography>
              )}
            </Grid>
          </Grid>

          {/* Quick Metrics */}
          <Grid container spacing={2} sx={{ mt: 2 }}>
            {reportData.test_coverage && (
              <>
                <Grid item xs={6} sm={3}>
                  <Card variant="outlined">
                    <CardContent sx={{ py: 1, px: 2, '&:last-child': { pb: 1 } }}>
                      <Typography variant="caption" color="text.secondary">
                        Line Coverage
                      </Typography>
                      <Typography variant="h6">
                        {reportData.test_coverage.line_coverage !== undefined
                          ? `${(reportData.test_coverage.line_coverage * 100).toFixed(1)}%`
                          : 'N/A'}
                      </Typography>
                    </CardContent>
                  </Card>
                </Grid>
                <Grid item xs={6} sm={3}>
                  <Card variant="outlined">
                    <CardContent sx={{ py: 1, px: 2, '&:last-child': { pb: 1 } }}>
                      <Typography variant="caption" color="text.secondary">
                        Test Pass Rate
                      </Typography>
                      <Typography variant="h6">
                        {(reportData.test_coverage.test_pass_rate * 100).toFixed(1)}%
                      </Typography>
                    </CardContent>
                  </Card>
                </Grid>
              </>
            )}
            {reportData.quality_summary && (
              <>
                <Grid item xs={6} sm={3}>
                  <Card variant="outlined">
                    <CardContent sx={{ py: 1, px: 2, '&:last-child': { pb: 1 } }}>
                      <Typography variant="caption" color="text.secondary">
                        DRE
                      </Typography>
                      <Typography variant="h6">
                        {reportData.quality_summary.defect_removal_efficiency !== undefined
                          ? `${(reportData.quality_summary.defect_removal_efficiency * 100).toFixed(1)}%`
                          : 'N/A'}
                      </Typography>
                    </CardContent>
                  </Card>
                </Grid>
                <Grid item xs={6} sm={3}>
                  <Card variant="outlined">
                    <CardContent sx={{ py: 1, px: 2, '&:last-child': { pb: 1 } }}>
                      <Typography variant="caption" color="text.secondary">
                        Escaped Defects
                      </Typography>
                      <Typography variant="h6">
                        {reportData.quality_summary.total_escaped_defects}
                      </Typography>
                    </CardContent>
                  </Card>
                </Grid>
              </>
            )}
          </Grid>

          {/* Recommendations Preview */}
          {reportData.recommendations.length > 0 && (
            <Box sx={{ mt: 3 }}>
              <Typography variant="subtitle2" gutterBottom>
                <StarIcon sx={{ fontSize: 16, mr: 0.5, verticalAlign: 'middle', color: 'warning.main' }} />
                Top Recommendations
              </Typography>
              {reportData.recommendations.slice(0, 3).map((rec, i) => (
                <Box key={i} sx={{ ml: 2, mb: 1, display: 'flex', alignItems: 'flex-start', gap: 1 }}>
                  <Chip
                    size="small"
                    label={rec.priority.toUpperCase()}
                    color={
                      rec.priority === 'critical' ? 'error' :
                      rec.priority === 'high' ? 'warning' :
                      rec.priority === 'medium' ? 'info' : 'default'
                    }
                    sx={{ minWidth: 70 }}
                  />
                  <Typography variant="body2">{rec.recommendation}</Typography>
                </Box>
              ))}
            </Box>
          )}
        </Paper>
      )}

      {/* Report Generation Options */}
      <Paper sx={{ p: 3 }}>
        <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
          <Typography variant="h6">Generate Report</Typography>
          <IconButton onClick={loadReportData} disabled={loading}>
            <RefreshIcon />
          </IconButton>
        </Box>

        {loading && <LinearProgress sx={{ mb: 2 }} />}
        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

        <Grid container spacing={3}>
          {/* Format Selection */}
          <Grid item xs={12} sm={4}>
            <FormControl fullWidth size="small">
              <InputLabel>Format</InputLabel>
              <Select
                value={format}
                label="Format"
                onChange={handleFormatChange}
              >
                <MenuItem value="pdf">
                  <Box display="flex" alignItems="center" gap={1}>
                    <PdfIcon fontSize="small" color="error" />
                    PDF Document
                  </Box>
                </MenuItem>
                <MenuItem value="excel">
                  <Box display="flex" alignItems="center" gap={1}>
                    <ExcelIcon fontSize="small" color="success" />
                    Excel Spreadsheet
                  </Box>
                </MenuItem>
                <MenuItem value="json">
                  <Box display="flex" alignItems="center" gap={1}>
                    <JsonIcon fontSize="small" color="primary" />
                    JSON Data
                  </Box>
                </MenuItem>
              </Select>
            </FormControl>
          </Grid>

          {/* Section Selection */}
          <Grid item xs={12} sm={8}>
            <Typography variant="subtitle2" gutterBottom>
              Include Sections
            </Typography>
            <FormGroup row>
              {REPORT_SECTIONS.map((section) => (
                <FormControlLabel
                  key={section}
                  control={
                    <Checkbox
                      size="small"
                      checked={selectedSections.includes(section)}
                      onChange={() => toggleSection(section)}
                    />
                  }
                  label={<Typography variant="body2">{SECTION_LABELS[section]}</Typography>}
                  sx={{ mr: 2 }}
                />
              ))}
            </FormGroup>
          </Grid>
        </Grid>

        {/* Action Buttons */}
        <Box display="flex" gap={2} mt={3}>
          <Button
            variant="contained"
            startIcon={generating ? <CircularProgress size={16} color="inherit" /> : <DownloadIcon />}
            onClick={handleDownload}
            disabled={generating || loading || !reportData}
          >
            {generating ? 'Generating...' : 'Download Report'}
          </Button>
          {format === 'pdf' && (
            <Button
              variant="outlined"
              startIcon={<PreviewIcon />}
              onClick={handlePreview}
              disabled={loading || !reportData}
            >
              Preview in Browser
            </Button>
          )}
        </Box>

        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 2 }}>
          Reports include quality metrics, test coverage, escaped defects analysis, and
          actionable recommendations based on your project&apos;s data.
        </Typography>
      </Paper>
    </Box>
  );
};

export default QualityReportPanel;
