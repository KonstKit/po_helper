import React from 'react';
import { NodeProps } from 'reactflow';
import { Chip } from '@mui/material';
import { FilterList as FilterIcon } from '@mui/icons-material';
import BaseNode from './BaseNode';

const FilterNode: React.FC<NodeProps> = ({ data, selected }) => {
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
      {data.config?.field && (
        <Chip
          label={`Field: ${data.config.field}`}
          size="small"
          sx={{ mt: 1, mr: 0.5 }}
        />
      )}
      {data.config?.operator && (
        <Chip
          label={`Operator: ${data.config.operator}`}
          size="small"
          sx={{ mt: 1, mr: 0.5 }}
        />
      )}
      {data.config?.value && (
        <Chip
          label={`Value: ${data.config.value}`}
          size="small"
          sx={{ mt: 1 }}
        />
      )}
    </BaseNode>
  );
};

export default FilterNode;
