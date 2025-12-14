import React, { useState } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  Box,
  Tabs,
  Tab,
  Alert,
  Typography,
} from '@mui/material';
import { Node, Edge } from 'reactflow';
import { Upload as UploadIcon, Download as DownloadIcon } from '@mui/icons-material';

interface ImportExportDialogProps {
  open: boolean;
  onClose: () => void;
  nodes: Node[];
  edges: Edge[];
  onImport: (nodes: Node[], edges: Edge[]) => void;
}

interface TabPanelProps {
  children?: React.ReactNode;
  index: number;
  value: number;
}

const TabPanel: React.FC<TabPanelProps> = ({ children, value, index }) => {
  return (
    <div role="tabpanel" hidden={value !== index}>
      {value === index && <Box sx={{ pt: 2 }}>{children}</Box>}
    </div>
  );
};

const ImportExportDialog: React.FC<ImportExportDialogProps> = ({
  open,
  onClose,
  nodes,
  edges,
  onImport,
}) => {
  const [tabValue, setTabValue] = useState(0);
  const [jsonText, setJsonText] = useState('');
  const [error, setError] = useState<string | null>(null);

  const handleExport = () => {
    const exportData = {
      version: '1.0',
      metadata: {
        name: 'Traceability Rule',
        created_at: new Date().toISOString(),
        author: 'user@example.com',
      },
      nodes,
      edges,
    };

    const jsonString = JSON.stringify(exportData, null, 2);
    setJsonText(jsonString);
    setTabValue(1); // Switch to Export tab
  };

  const handleImport = () => {
    setError(null);

    try {
      const importData = JSON.parse(jsonText);

      // Basic validation
      if (!importData.nodes || !Array.isArray(importData.nodes)) {
        throw new Error('Invalid format: "nodes" array is required');
      }
      if (!importData.edges || !Array.isArray(importData.edges)) {
        throw new Error('Invalid format: "edges" array is required');
      }

      onImport(importData.nodes, importData.edges);
      onClose();
      setJsonText('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Invalid JSON format');
    }
  };

  const handleDownload = () => {
    const blob = new Blob([jsonText], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `traceability-rule-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleFileUpload = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (e) => {
      const content = e.target?.result as string;
      setJsonText(content);
    };
    reader.readAsText(file);
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>Import / Export Rule</DialogTitle>
      <DialogContent>
        <Tabs value={tabValue} onChange={(_, newValue) => setTabValue(newValue)}>
          <Tab label="Import" />
          <Tab label="Export" />
        </Tabs>

        <TabPanel value={tabValue} index={0}>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Import a rule from JSON file or paste JSON directly
          </Typography>

          <Button
            variant="outlined"
            component="label"
            startIcon={<UploadIcon />}
            sx={{ mb: 2 }}
          >
            Upload JSON File
            <input
              type="file"
              accept=".json"
              hidden
              onChange={handleFileUpload}
            />
          </Button>

          <TextField
            fullWidth
            multiline
            rows={12}
            value={jsonText}
            onChange={(e) => setJsonText(e.target.value)}
            placeholder="Paste JSON here..."
            variant="outlined"
          />

          {error && (
            <Alert severity="error" sx={{ mt: 2 }}>
              {error}
            </Alert>
          )}
        </TabPanel>

        <TabPanel value={tabValue} index={1}>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Export current rule as JSON
          </Typography>

          {jsonText ? (
            <>
              <TextField
                fullWidth
                multiline
                rows={12}
                value={jsonText}
                InputProps={{ readOnly: true }}
                variant="outlined"
              />
              <Button
                variant="outlined"
                startIcon={<DownloadIcon />}
                onClick={handleDownload}
                sx={{ mt: 2 }}
              >
                Download JSON File
              </Button>
            </>
          ) : (
            <Alert severity="info">
              Click "Export Current Rule" to generate JSON
            </Alert>
          )}
        </TabPanel>
      </DialogContent>

      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        {tabValue === 0 ? (
          <Button
            variant="contained"
            onClick={handleImport}
            disabled={!jsonText}
          >
            Import
          </Button>
        ) : (
          <Button
            variant="contained"
            onClick={handleExport}
          >
            Export Current Rule
          </Button>
        )}
      </DialogActions>
    </Dialog>
  );
};

export default ImportExportDialog;
