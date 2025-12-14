import React from 'react';
import { NodeProps } from 'reactflow';
import { Chip } from '@mui/material';
import { Code as CodeIcon } from '@mui/icons-material';
import BaseNode from './BaseNode';

const CommitSourceNode: React.FC<NodeProps> = ({ data, selected }) => {
  return (
    <BaseNode
      data={data}
      selected={selected}
      icon={<CodeIcon fontSize="small" />}
      color="primary"
      category="Source Node"
      hasOutput={true}
    >
      {data.filters?.branch && (
        <Chip
          label={`Branch: ${data.filters.branch}`}
          size="small"
          sx={{ mt: 1, mr: 0.5 }}
        />
      )}
      {data.filters?.author && (
        <Chip
          label={`Author: ${data.filters.author}`}
          size="small"
          sx={{ mt: 1, mr: 0.5 }}
        />
      )}
      {data.filters?.after_date && (
        <Chip
          label={`After: ${data.filters.after_date}`}
          size="small"
          sx={{ mt: 1 }}
        />
      )}
    </BaseNode>
  );
};

export default CommitSourceNode;
