/**
 * Traceability Rules UI - Component Structure Mockup
 *
 * This file shows the component hierarchy and props structure.
 * NOT executable code - just design reference.
 */

import React from 'react';

// ============================================================================
// 1. MAIN PAGE COMPONENT
// ============================================================================

interface TraceabilityRulesPageProps {}

const TraceabilityRulesPage: React.FC = () => {
  const [view, setView] = useState<'gallery' | 'list' | 'create'>('gallery');
  const [rules, setRules] = useState<TraceabilityRule[]>([]);
  const [selectedRule, setSelectedRule] = useState<TraceabilityRule | null>(null);

  return (
    <Box>
      {/* Header with tabs */}
      <Tabs value={view} onChange={(e, v) => setView(v)}>
        <Tab label="Templates" value="gallery" />
        <Tab label="My Rules" value="list" />
        <Tab label="Create New" value="create" />
      </Tabs>

      {/* Content */}
      {view === 'gallery' && <TemplateGallery onSelect={handleTemplateSelect} />}
      {view === 'list' && <RuleList rules={rules} onEdit={setSelectedRule} />}
      {view === 'create' && <RuleBuilder rule={selectedRule} onSave={handleSave} />}
    </Box>
  );
};

// ============================================================================
// 2. TEMPLATE GALLERY COMPONENT
// ============================================================================

interface TemplateGalleryProps {
  onSelect: (template: RuleTemplate) => void;
}

const TemplateGallery: React.FC<TemplateGalleryProps> = ({ onSelect }) => {
  const templates: RuleTemplate[] = [
    {
      id: 'commit_to_subtask',
      name: 'Commit → Sub-task',
      description: 'Links commits to Jira sub-tasks via issue keys',
      icon: '📝',
      coverage: '90%',
      confidence: 'High',
      preview: {
        input: 'feat: WAB-123 add authentication',
        output: 'Commit → WAB-123 (Sub-task)',
      },
      config: { /* ... */ }
    },
    // ... more templates
  ];

  return (
    <Grid container spacing={3}>
      {templates.map(template => (
        <Grid item xs={12} md={6} lg={4} key={template.id}>
          <TemplateCard template={template} onClick={() => onSelect(template)} />
        </Grid>
      ))}
    </Grid>
  );
};

// ============================================================================
// 3. TEMPLATE CARD COMPONENT
// ============================================================================

interface TemplateCardProps {
  template: RuleTemplate;
  onClick: () => void;
}

const TemplateCard: React.FC<TemplateCardProps> = ({ template, onClick }) => {
  return (
    <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <CardHeader
        avatar={<Typography variant="h3">{template.icon}</Typography>}
        title={template.name}
        subheader={template.description}
      />
      <CardContent sx={{ flexGrow: 1 }}>
        <Stack spacing={1}>
          <Chip label={`Coverage: ${template.coverage}`} size="small" color="primary" />
          <Chip
            label={`Confidence: ${template.confidence}`}
            size="small"
            color={template.confidence === 'High' ? 'success' : 'warning'}
          />

          <Divider />

          <Typography variant="caption" color="text.secondary">
            Preview:
          </Typography>
          <Box sx={{ bgcolor: 'background.default', p: 1, borderRadius: 1 }}>
            <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
              {template.preview.input}
            </Typography>
            <Typography variant="caption" color="success.main">
              → {template.preview.output}
            </Typography>
          </Box>
        </Stack>
      </CardContent>
      <CardActions>
        <Button fullWidth variant="contained" onClick={onClick}>
          Use Template
        </Button>
      </CardActions>
    </Card>
  );
};

// ============================================================================
// 4. RULE BUILDER (FORM MODE)
// ============================================================================

interface RuleBuilderProps {
  rule?: TraceabilityRule | null;
  template?: RuleTemplate;
  onSave: (rule: TraceabilityRule) => void;
  onCancel: () => void;
}

const RuleBuilder: React.FC<RuleBuilderProps> = ({ rule, template, onSave, onCancel }) => {
  const [formData, setFormData] = useState<Partial<TraceabilityRule>>(
    rule || template?.config || {}
  );
  const [previewResult, setPreviewResult] = useState<PreviewResult | null>(null);
  const [mode, setMode] = useState<'form' | 'yaml'>('form');

  return (
    <Box>
      {/* Mode selector */}
      <ToggleButtonGroup value={mode} exclusive onChange={(e, v) => setMode(v)}>
        <ToggleButton value="form">Form</ToggleButton>
        <ToggleButton value="yaml">YAML</ToggleButton>
      </ToggleButtonGroup>

      {mode === 'form' ? (
        <FormBuilder data={formData} onChange={setFormData} />
      ) : (
        <YamlEditor data={formData} onChange={setFormData} />
      )}

      {/* Preview panel */}
      <PreviewPanel rule={formData} result={previewResult} />

      {/* Actions */}
      <Stack direction="row" spacing={2} sx={{ mt: 3 }}>
        <Button onClick={onCancel}>Cancel</Button>
        <Button variant="outlined" onClick={handlePreview}>
          Preview
        </Button>
        <Button variant="contained" onClick={() => onSave(formData as TraceabilityRule)}>
          Save Rule
        </Button>
      </Stack>
    </Box>
  );
};

// ============================================================================
// 5. FORM BUILDER (EXPANDABLE SECTIONS)
// ============================================================================

interface FormBuilderProps {
  data: Partial<TraceabilityRule>;
  onChange: (data: Partial<TraceabilityRule>) => void;
}

const FormBuilder: React.FC<FormBuilderProps> = ({ data, onChange }) => {
  const [expanded, setExpanded] = useState<string>('basic');

  return (
    <Box>
      {/* Basic Information */}
      <Accordion expanded={expanded === 'basic'} onChange={() => setExpanded('basic')}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography>📋 Basic Information</Typography>
        </AccordionSummary>
        <AccordionDetails>
          <Stack spacing={2}>
            <TextField
              label="Rule Name"
              value={data.name || ''}
              onChange={(e) => onChange({ ...data, name: e.target.value })}
              fullWidth
              required
            />
            <TextField
              label="Description"
              value={data.description || ''}
              onChange={(e) => onChange({ ...data, description: e.target.value })}
              multiline
              rows={2}
              fullWidth
            />
            <Stack direction="row" spacing={2}>
              <FormControlLabel
                control={
                  <Switch
                    checked={data.enabled ?? true}
                    onChange={(e) => onChange({ ...data, enabled: e.target.checked })}
                  />
                }
                label="Enabled"
              />
              <TextField
                label="Priority"
                type="number"
                value={data.priority || 100}
                onChange={(e) => onChange({ ...data, priority: parseInt(e.target.value) })}
                sx={{ width: 120 }}
              />
            </Stack>
          </Stack>
        </AccordionDetails>
      </Accordion>

      {/* Artifacts & Direction */}
      <Accordion expanded={expanded === 'artifacts'} onChange={() => setExpanded('artifacts')}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography>🎯 Artifacts & Direction</Typography>
        </AccordionSummary>
        <AccordionDetails>
          <Grid container spacing={2} alignItems="center">
            <Grid item xs={5}>
              <FormControl fullWidth>
                <InputLabel>Source Type</InputLabel>
                <Select
                  value={data.source_artifact_type || ''}
                  onChange={(e) => onChange({ ...data, source_artifact_type: e.target.value })}
                >
                  <MenuItem value="Commit">📝 Commit</MenuItem>
                  <MenuItem value="JiraIssue">🎫 Jira Issue</MenuItem>
                  <MenuItem value="ConfluencePage">📄 Confluence Page</MenuItem>
                  <MenuItem value="TestCase">🧪 Test Case</MenuItem>
                </Select>
              </FormControl>
            </Grid>

            <Grid item xs={2} sx={{ textAlign: 'center' }}>
              <ArrowForwardIcon fontSize="large" color="primary" />
            </Grid>

            <Grid item xs={5}>
              <FormControl fullWidth>
                <InputLabel>Target Type</InputLabel>
                <Select
                  value={data.target_artifact_type || ''}
                  onChange={(e) => onChange({ ...data, target_artifact_type: e.target.value })}
                >
                  <MenuItem value="JiraIssue">🎫 Jira Issue</MenuItem>
                  <MenuItem value="ConfluencePage">📄 Confluence Page</MenuItem>
                  <MenuItem value="TestCase">🧪 Test Case</MenuItem>
                  <MenuItem value="Commit">📝 Commit</MenuItem>
                </Select>
              </FormControl>
            </Grid>

            <Grid item xs={12}>
              <FormControlLabel
                control={
                  <Checkbox
                    checked={data.create_reverse_link ?? false}
                    onChange={(e) => onChange({ ...data, create_reverse_link: e.target.checked })}
                  />
                }
                label="Create reverse link (bidirectional)"
              />
              {data.create_reverse_link && (
                <TextField
                  label="Reverse Link Type"
                  value={data.reverse_link_type || ''}
                  onChange={(e) => onChange({ ...data, reverse_link_type: e.target.value })}
                  placeholder="e.g., implemented_by"
                  size="small"
                  sx={{ ml: 4, width: 300 }}
                />
              )}
            </Grid>
          </Grid>
        </AccordionDetails>
      </Accordion>

      {/* Matching Strategy */}
      <Accordion expanded={expanded === 'strategy'} onChange={() => setExpanded('strategy')}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography>🔍 Matching Strategy</Typography>
        </AccordionSummary>
        <AccordionDetails>
          <Stack spacing={2}>
            <FormControl fullWidth>
              <InputLabel>Strategy</InputLabel>
              <Select
                value={data.match_strategy || ''}
                onChange={(e) => onChange({ ...data, match_strategy: e.target.value as MatchStrategy })}
              >
                <MenuItem value="jira_key">JIRA Key Pattern</MenuItem>
                <MenuItem value="regex">Custom Regex</MenuItem>
                <MenuItem value="title_match">Title Similarity</MenuItem>
                <MenuItem value="api_link">API Link Field</MenuItem>
                <MenuItem value="composite">Composite (Multiple Strategies)</MenuItem>
              </Select>
            </FormControl>

            {/* Strategy-specific config */}
            <StrategyConfigEditor
              strategy={data.match_strategy}
              config={data.match_config || {}}
              onChange={(config) => onChange({ ...data, match_config: config })}
            />
          </Stack>
        </AccordionDetails>
      </Accordion>

      {/* Filters */}
      <Accordion expanded={expanded === 'filters'} onChange={() => setExpanded('filters')}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography>🎛️ Filters (Optional)</Typography>
        </AccordionSummary>
        <AccordionDetails>
          <Stack spacing={2}>
            <JsonEditor
              label="Source Filter"
              value={data.source_filter || {}}
              onChange={(v) => onChange({ ...data, source_filter: v })}
              placeholder='{"branch_pattern": "feature/*"}'
            />
            <JsonEditor
              label="Target Filter"
              value={data.target_filter || {}}
              onChange={(v) => onChange({ ...data, target_filter: v })}
              placeholder='{"jira_issue_type": ["Sub-task", "Task"]}'
            />
          </Stack>
        </AccordionDetails>
      </Accordion>

      {/* Confidence & Review */}
      <Accordion expanded={expanded === 'confidence'} onChange={() => setExpanded('confidence')}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography>📊 Confidence & Review</Typography>
        </AccordionSummary>
        <AccordionDetails>
          <Stack spacing={2}>
            <Box>
              <Typography gutterBottom>Base Confidence: {data.base_confidence || 80}%</Typography>
              <Slider
                value={data.base_confidence || 80}
                onChange={(e, v) => onChange({ ...data, base_confidence: v as number })}
                min={0}
                max={100}
                marks={[
                  { value: 0, label: 'Low' },
                  { value: 50, label: 'Medium' },
                  { value: 85, label: 'High' }
                ]}
                valueLabelDisplay="auto"
              />
            </Box>

            <FormControlLabel
              control={
                <Checkbox
                  checked={data.require_manual_review ?? false}
                  onChange={(e) => onChange({ ...data, require_manual_review: e.target.checked })}
                />
              }
              label="Require manual review for medium-confidence links"
            />

            {data.require_manual_review && (
              <TextField
                label="Review threshold"
                type="number"
                value={data.review_threshold || 50}
                onChange={(e) => onChange({ ...data, review_threshold: parseInt(e.target.value) })}
                helperText="Links below this confidence will be queued for review"
                InputProps={{ endAdornment: '%' }}
              />
            )}
          </Stack>
        </AccordionDetails>
      </Accordion>
    </Box>
  );
};

// ============================================================================
// 6. STRATEGY CONFIG EDITOR (DYNAMIC BASED ON STRATEGY)
// ============================================================================

interface StrategyConfigEditorProps {
  strategy: MatchStrategy | undefined;
  config: Record<string, any>;
  onChange: (config: Record<string, any>) => void;
}

const StrategyConfigEditor: React.FC<StrategyConfigEditorProps> = ({ strategy, config, onChange }) => {
  if (strategy === 'jira_key') {
    return (
      <Box sx={{ bgcolor: 'background.default', p: 2, borderRadius: 1 }}>
        <Typography variant="subtitle2" gutterBottom>JIRA Key Settings</Typography>

        <FormGroup>
          <FormLabel>Search in:</FormLabel>
          <FormControlLabel
            control={
              <Checkbox
                checked={config.search_in?.includes('message')}
                onChange={(e) => {
                  const searchIn = e.target.checked
                    ? [...(config.search_in || []), 'message']
                    : config.search_in?.filter(s => s !== 'message');
                  onChange({ ...config, search_in: searchIn });
                }}
              />
            }
            label="Commit message"
          />
          <FormControlLabel
            control={
              <Checkbox
                checked={config.search_in?.includes('branch_name')}
                onChange={(e) => {
                  const searchIn = e.target.checked
                    ? [...(config.search_in || []), 'branch_name']
                    : config.search_in?.filter(s => s !== 'branch_name');
                  onChange({ ...config, search_in: searchIn });
                }}
              />
            }
            label="Branch name"
          />
        </FormGroup>

        <TextField
          label="Pattern (Regex)"
          value={config.pattern || r"\b[A-Z][A-Z0-9_]+-[0-9]+\b"}
          onChange={(e) => onChange({ ...config, pattern: e.target.value })}
          fullWidth
          sx={{ mt: 2 }}
          helperText="Modern Jira pattern (supports numbers/underscores in project key)"
        />

        <Stack direction="row" spacing={2} sx={{ mt: 2 }}>
          <FormControlLabel
            control={
              <Switch
                checked={config.case_sensitive ?? false}
                onChange={(e) => onChange({ ...config, case_sensitive: e.target.checked })}
              />
            }
            label="Case sensitive"
          />
          <FormControlLabel
            control={
              <Switch
                checked={config.must_be_uppercase ?? true}
                onChange={(e) => onChange({ ...config, must_be_uppercase: e.target.checked })}
              />
            }
            label="Must be uppercase"
          />
        </Stack>

        {/* Live preview */}
        <TestRegexInput pattern={config.pattern} />
      </Box>
    );
  }

  if (strategy === 'api_link') {
    return (
      <Box sx={{ bgcolor: 'background.default', p: 2, borderRadius: 1 }}>
        <Typography variant="subtitle2" gutterBottom>API Link Settings</Typography>

        <FormControl fullWidth>
          <InputLabel>Jira Field</InputLabel>
          <Select
            value={config.jira_field || ''}
            onChange={(e) => onChange({ ...config, jira_field: e.target.value })}
          >
            <MenuItem value="parent">Parent (issue.fields.parent)</MenuItem>
            <MenuItem value="issuelinks">Issue Links (issue.fields.issuelinks)</MenuItem>
            <MenuItem value="subtasks">Sub-tasks (issue.fields.subtasks)</MenuItem>
            <MenuItem value="customfield_10000">Custom Field</MenuItem>
          </Select>
        </FormControl>
      </Box>
    );
  }

  // ... other strategies

  return null;
};

// ============================================================================
// 7. PREVIEW PANEL
// ============================================================================

interface PreviewPanelProps {
  rule: Partial<TraceabilityRule>;
  result: PreviewResult | null;
}

const PreviewPanel: React.FC<PreviewPanelProps> = ({ rule, result }) => {
  return (
    <Paper sx={{ p: 2, mt: 3, bgcolor: 'grey.50' }}>
      <Typography variant="h6" gutterBottom>🧪 Preview</Typography>

      <TextField
        label="Test Input"
        placeholder="e.g., feat: WAB-123 add user authentication"
        fullWidth
        multiline
        rows={2}
      />

      <Button variant="outlined" sx={{ mt: 1 }}>
        Run Preview
      </Button>

      {result && (
        <Box sx={{ mt: 2, p: 2, bgcolor: 'white', borderRadius: 1 }}>
          {result.matched ? (
            <Alert severity="success">
              <Typography variant="body2">
                ✓ Match found: {result.target_id}
              </Typography>
              <Typography variant="caption">
                Confidence: {result.confidence}%
              </Typography>
            </Alert>
          ) : (
            <Alert severity="warning">
              No match found with this rule
            </Alert>
          )}
        </Box>
      )}
    </Paper>
  );
};

// ============================================================================
// 8. TYPE DEFINITIONS
// ============================================================================

interface TraceabilityRule {
  id?: number;
  name: string;
  description?: string;
  enabled: boolean;
  priority: number;
  source_artifact_type: string;
  target_artifact_type: string;
  match_strategy: MatchStrategy;
  match_config: Record<string, any>;
  source_filter?: Record<string, any>;
  target_filter?: Record<string, any>;
  link_type: string;
  create_reverse_link?: boolean;
  reverse_link_type?: string;
  base_confidence: number;
  require_manual_review?: boolean;
  review_threshold?: number;
}

type MatchStrategy = 'jira_key' | 'regex' | 'title_match' | 'api_link' | 'composite';

interface RuleTemplate {
  id: string;
  name: string;
  description: string;
  icon: string;
  coverage: string;
  confidence: string;
  preview: {
    input: string;
    output: string;
  };
  config: Partial<TraceabilityRule>;
}

interface PreviewResult {
  matched: boolean;
  target_id?: string;
  confidence?: number;
  details?: string;
}
