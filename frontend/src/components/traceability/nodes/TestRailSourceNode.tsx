import React from 'react';
import { NodeProps } from 'reactflow';
import { Chip } from '@mui/material';
import { FactCheck as TestRailIcon } from '@mui/icons-material';

import BaseNode from './BaseNode';

const TestRailSourceNode: React.FC<NodeProps> = ({ data, selected }) => {
  return (
    <BaseNode
      data={data}
      selected={selected}
      icon={<TestRailIcon fontSize="small" />}
      color="info"
      category="Source Node"
      hasOutput={true}
    >
      {data.filters?.project_id && (
        <Chip label={`Project: ${data.filters.project_id}`} size="small" sx={{ mt: 1, mr: 0.5 }} />
      )}
      {data.filters?.suite_id && (
        <Chip label={`Suite: ${data.filters.suite_id}`} size="small" sx={{ mt: 1, mr: 0.5 }} />
      )}
      {Array.isArray(data.filters?.status) && data.filters.status.length > 0 && (
        <Chip label={`Status: ${data.filters.status.join(', ')}`} size="small" sx={{ mt: 1 }} />
      )}
    </BaseNode>
  );
};

export default TestRailSourceNode;
