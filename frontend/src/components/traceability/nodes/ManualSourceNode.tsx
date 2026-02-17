import React from 'react';
import { NodeProps } from 'reactflow';
import { Chip } from '@mui/material';
import { EditNote as ManualIcon } from '@mui/icons-material';

import BaseNode from './BaseNode';

const ManualSourceNode: React.FC<NodeProps> = ({ data, selected }) => {
  return (
    <BaseNode
      data={data}
      selected={selected}
      icon={<ManualIcon fontSize="small" />}
      color="info"
      category="Source Node"
      hasOutput={true}
    >
      {Array.isArray(data.config?.artifact_ids) && data.config.artifact_ids.length > 0 && (
        <Chip label={`IDs: ${data.config.artifact_ids.length}`} size="small" sx={{ mt: 1, mr: 0.5 }} />
      )}
      {Array.isArray(data.config?.external_ids) && data.config.external_ids.length > 0 && (
        <Chip
          label={`External IDs: ${data.config.external_ids.length}`}
          size="small"
          sx={{ mt: 1, mr: 0.5 }}
        />
      )}
      {Array.isArray(data.config?.artifact_types) && data.config.artifact_types.length > 0 && (
        <Chip label={`Types: ${data.config.artifact_types.join(', ')}`} size="small" sx={{ mt: 1 }} />
      )}
    </BaseNode>
  );
};

export default ManualSourceNode;
