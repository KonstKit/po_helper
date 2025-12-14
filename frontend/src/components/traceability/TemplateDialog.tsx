import React, { useState } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Grid,
  Card,
  CardContent,
  CardActions,
  Typography,
  Chip,
  Box,
  Tabs,
  Tab,
} from '@mui/material';
import { ruleTemplates, applyTemplate, RuleTemplate } from '../../utils/ruleTemplates';
import { Node, Edge } from 'reactflow';

interface TemplateDialogProps {
  open: boolean;
  onClose: () => void;
  onApplyTemplate: (nodes: Node[], edges: Edge[]) => void;
}

const TemplateDialog: React.FC<TemplateDialogProps> = ({ open, onClose, onApplyTemplate }) => {
  const [selectedCategory, setSelectedCategory] = useState<'all' | 'basic' | 'advanced'>('all');

  const filteredTemplates = selectedCategory === 'all'
    ? ruleTemplates
    : ruleTemplates.filter((t) => t.category === selectedCategory);

  const handleApply = (template: RuleTemplate) => {
    const { nodes, edges } = applyTemplate(template);
    onApplyTemplate(nodes, edges);
    onClose();
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>Choose a Template</DialogTitle>
      <DialogContent>
        <Tabs
          value={selectedCategory}
          onChange={(_, newValue) => setSelectedCategory(newValue)}
          sx={{ mb: 2 }}
        >
          <Tab label="All Templates" value="all" />
          <Tab label="Basic" value="basic" />
          <Tab label="Advanced" value="advanced" />
        </Tabs>

        <Grid container spacing={2}>
          {filteredTemplates.map((template) => (
            <Grid item xs={12} sm={6} key={template.id}>
              <Card variant="outlined">
                <CardContent>
                  <Typography variant="h6" gutterBottom>
                    {template.name}
                  </Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                    {template.description}
                  </Typography>
                  <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                    <Chip
                      label={template.category}
                      size="small"
                      color={template.category === 'basic' ? 'primary' : 'secondary'}
                    />
                    {template.tags.map((tag) => (
                      <Chip key={tag} label={tag} size="small" variant="outlined" />
                    ))}
                  </Box>
                  <Typography variant="caption" color="text.secondary" sx={{ mt: 2, display: 'block' }}>
                    {template.nodes.length} nodes, {template.edges.length} connections
                  </Typography>
                </CardContent>
                <CardActions>
                  <Button size="small" onClick={() => handleApply(template)}>
                    Use Template
                  </Button>
                </CardActions>
              </Card>
            </Grid>
          ))}
        </Grid>

        {filteredTemplates.length === 0 && (
          <Typography variant="body2" color="text.secondary" align="center" sx={{ py: 4 }}>
            No templates found in this category
          </Typography>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
      </DialogActions>
    </Dialog>
  );
};

export default TemplateDialog;
