import React from 'react';
import {
  Box,
  Paper,
  Typography,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  Divider,
  Button,
} from '@mui/material';
import {
  Code as CodeIcon,
  BugReport as BugIcon,
  Description as DescIcon,
  FilterAlt as FilterIcon,
  FilterList as FilterListIcon,
  CallSplit as DecisionIcon,
  Link as LinkIcon,
  Upload as UploadIcon,
  Download as DownloadIcon,
  LibraryBooks as TemplateIcon,
} from '@mui/icons-material';

interface ToolboxProps {
  onImportExportClick: () => void;
  onTemplateClick: () => void;
}

interface NodeTemplate {
  type: string;
  label: string;
  icon: React.ReactNode;
  category: 'source' | 'processor' | 'action';
  defaultData: NodeTemplateData;
}

type NodeTemplateData = Record<string, unknown>;

const nodeTemplates: NodeTemplate[] = [
  // Source Nodes
  {
    type: 'commitSource',
    label: 'Git Commit',
    icon: <CodeIcon />,
    category: 'source',
    defaultData: {
      label: 'Git Commit',
      filters: {
        branch: '',
        author: '',
        after_date: '',
      },
    },
  },
  {
    type: 'jiraIssueSource',
    label: 'Jira Issue',
    icon: <BugIcon />,
    category: 'source',
    defaultData: {
      label: 'Jira Issue',
      filters: {
        issue_type: [],
        status: [],
        project: '',
      },
    },
  },
  {
    type: 'confluenceSource',
    label: 'Confluence Page',
    icon: <DescIcon />,
    category: 'source',
    defaultData: {
      label: 'Confluence Page',
      filters: {
        space: '',
        labels: [],
      },
    },
  },

  // Processor Nodes
  {
    type: 'jiraKeyExtractor',
    label: 'Jira Key Extractor',
    icon: <FilterIcon />,
    category: 'processor',
    defaultData: {
      label: 'Extract Jira Keys',
      config: {
        search_in: ['message'],
        pattern: '\\b[A-Z][A-Z0-9_]+-[0-9]+\\b',
        case_sensitive: false,
        must_be_uppercase: true,
        extract_multiple: true,
      },
    },
  },
  {
    type: 'filterNode',
    label: 'Filter',
    icon: <FilterListIcon />,
    category: 'processor',
    defaultData: {
      label: 'Filter Artifacts',
      config: {
        field: '',
        operator: 'equals',
        value: '',
      },
    },
  },
  {
    type: 'decisionNode',
    label: 'Decision',
    icon: <DecisionIcon />,
    category: 'processor',
    defaultData: {
      label: 'Decision',
      config: {
        condition_type: 'confidence_threshold',
        threshold: 85,
      },
    },
  },

  // Action Nodes
  {
    type: 'createLinkAction',
    label: 'Create Link',
    icon: <LinkIcon />,
    category: 'action',
    defaultData: {
      label: 'Create Link',
      config: {
        link_type: 'relates_to',
        bidirectional: false,
        reverse_link_type: '',
      },
    },
  },
];

const Toolbox: React.FC<ToolboxProps> = ({ onImportExportClick, onTemplateClick }) => {
  const onDragStart = (event: React.DragEvent, nodeType: string, nodeData: NodeTemplateData) => {
    event.dataTransfer.setData('application/reactflow', nodeType);
    event.dataTransfer.setData('application/nodedata', JSON.stringify(nodeData));
    event.dataTransfer.effectAllowed = 'move';
  };

  const renderNodesByCategory = (category: string) => {
    return nodeTemplates
      .filter((template) => template.category === category)
      .map((template) => (
        <ListItem
          key={template.type}
          draggable
          onDragStart={(e) => onDragStart(e, template.type, template.defaultData)}
          sx={{
            cursor: 'grab',
            '&:hover': {
              bgcolor: 'action.hover',
            },
            '&:active': {
              cursor: 'grabbing',
            },
          }}
        >
          <ListItemIcon>{template.icon}</ListItemIcon>
          <ListItemText primary={template.label} />
        </ListItem>
      ));
  };

  return (
    <Paper
      sx={{
        width: 250,
        height: '100%',
        borderRadius: 0,
        overflowY: 'auto',
        borderRight: 1,
        borderColor: 'divider',
      }}
    >
      <Box sx={{ p: 2 }}>
        <Typography variant="h6" gutterBottom>
          Toolbox
        </Typography>

        {/* Templates Button */}
        <Button
          size="small"
          startIcon={<TemplateIcon />}
          variant="contained"
          fullWidth
          onClick={onTemplateClick}
          sx={{ mb: 2 }}
        >
          Templates
        </Button>

        {/* Import/Export Buttons */}
        <Box sx={{ mb: 2, display: 'flex', gap: 1 }}>
          <Button
            size="small"
            startIcon={<UploadIcon />}
            variant="outlined"
            fullWidth
            onClick={onImportExportClick}
          >
            Import
          </Button>
          <Button
            size="small"
            startIcon={<DownloadIcon />}
            variant="outlined"
            fullWidth
            onClick={onImportExportClick}
          >
            Export
          </Button>
        </Box>

        <Divider sx={{ my: 2 }} />

        {/* Source Nodes */}
        <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>
          Source Nodes
        </Typography>
        <List dense>{renderNodesByCategory('source')}</List>

        <Divider sx={{ my: 2 }} />

        {/* Processor Nodes */}
        <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>
          Processor Nodes
        </Typography>
        <List dense>{renderNodesByCategory('processor')}</List>

        <Divider sx={{ my: 2 }} />

        {/* Action Nodes */}
        <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>
          Action Nodes
        </Typography>
        <List dense>{renderNodesByCategory('action')}</List>
      </Box>
    </Paper>
  );
};

export default Toolbox;
