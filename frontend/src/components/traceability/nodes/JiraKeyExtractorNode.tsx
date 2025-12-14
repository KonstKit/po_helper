import React from 'react';
import { NodeProps } from 'reactflow';
import { Chip } from '@mui/material';
import { FilterAlt as FilterIcon } from '@mui/icons-material';
import BaseNode from './BaseNode';

const JiraKeyExtractorNode: React.FC<NodeProps> = ({ data, selected }) => {
  return (
    <BaseNode
      data={data}
      selected={selected}
      icon={<FilterIcon fontSize="small" />}
      color="secondary"
      category="Processor Node"
      hasInput={true}
      hasOutput={true}
    >
      {data.config?.search_in && (
        <Chip
          label={`Search: ${data.config.search_in.join(', ')}`}
          size="small"
          sx={{ mt: 1, mr: 0.5 }}
        />
      )}
      {data.config?.pattern && (
        <Chip
          label={`Pattern: ${data.config.pattern}`}
          size="small"
          sx={{ mt: 1 }}
        />
      )}
    </BaseNode>
  );
};

export default JiraKeyExtractorNode;
