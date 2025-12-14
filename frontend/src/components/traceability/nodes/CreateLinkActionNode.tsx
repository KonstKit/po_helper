import React from 'react';
import { NodeProps } from 'reactflow';
import { Chip } from '@mui/material';
import { Link as LinkIcon } from '@mui/icons-material';
import BaseNode from './BaseNode';

const CreateLinkActionNode: React.FC<NodeProps> = ({ data, selected }) => {
  return (
    <BaseNode
      data={data}
      selected={selected}
      icon={<LinkIcon fontSize="small" />}
      color="warning"
      category="Action Node"
      hasInput={true}
    >
      {data.config?.link_type && (
        <Chip
          label={`Type: ${data.config.link_type}`}
          size="small"
          sx={{ mt: 1, mr: 0.5 }}
        />
      )}
      {data.config?.bidirectional && (
        <Chip
          label="Bidirectional"
          size="small"
          color="info"
          sx={{ mt: 1 }}
        />
      )}
    </BaseNode>
  );
};

export default CreateLinkActionNode;
