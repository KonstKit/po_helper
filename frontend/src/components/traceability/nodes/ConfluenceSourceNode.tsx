import React from 'react';
import { NodeProps } from 'reactflow';
import { Chip } from '@mui/material';
import { Description as DescIcon } from '@mui/icons-material';
import BaseNode from './BaseNode';

const ConfluenceSourceNode: React.FC<NodeProps> = ({ data, selected }) => {
  return (
    <BaseNode
      data={data}
      selected={selected}
      icon={<DescIcon fontSize="small" />}
      color="info"
      category="Source Node"
      hasOutput={true}
    >
      {data.filters?.space && (
        <Chip
          label={`Space: ${data.filters.space}`}
          size="small"
          sx={{ mt: 1, mr: 0.5 }}
        />
      )}
      {data.filters?.labels?.length > 0 && (
        <Chip
          label={`Labels: ${data.filters.labels.join(', ')}`}
          size="small"
          sx={{ mt: 1 }}
        />
      )}
    </BaseNode>
  );
};

export default ConfluenceSourceNode;
