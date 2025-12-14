import React from 'react';
import { Handle, Position, NodeProps } from 'reactflow';
import { Chip, Paper, Box, Typography } from '@mui/material';
import { CallSplit as DecisionIcon } from '@mui/icons-material';

const DecisionNode: React.FC<NodeProps> = ({ data, selected }) => {
  return (
    <Paper
      elevation={selected ? 8 : 2}
      sx={{
        minWidth: 200,
        border: selected ? 3 : 1,
        borderColor: selected ? '#00ff00' : 'divider',
        borderRadius: 1,
        overflow: 'hidden',
        position: 'relative',
      }}
    >
      <Box
        sx={{
          bgcolor: 'info.main',
          color: 'info.contrastText',
          p: 1,
          display: 'flex',
          alignItems: 'center',
          gap: 1,
        }}
      >
        <DecisionIcon fontSize="small" />
        <Typography variant="subtitle2">{data.label}</Typography>
      </Box>

      <Box sx={{ p: 2 }}>
        <Typography variant="caption" color="text.secondary" display="block">
          Decision Node
        </Typography>

        {data.config?.condition_type && (
          <Chip
            label={data.config.condition_type}
            size="small"
            sx={{ mt: 1, mr: 0.5 }}
          />
        )}
        {data.config?.threshold !== undefined && (
          <Chip
            label={`Threshold: ${data.config.threshold}`}
            size="small"
            sx={{ mt: 1 }}
          />
        )}
      </Box>

      <Handle
        type="target"
        position={Position.Left}
        style={{ width: 12, height: 12, border: '2px solid white' }}
      />
      <Handle
        type="source"
        position={Position.Right}
        id="true"
        style={{ width: 12, height: 12, background: '#4caf50', border: '2px solid white', top: '40%' }}
      />
      <Handle
        type="source"
        position={Position.Right}
        id="false"
        style={{ width: 12, height: 12, background: '#f44336', border: '2px solid white', top: '60%' }}
      />
    </Paper>
  );
};

export default DecisionNode;
