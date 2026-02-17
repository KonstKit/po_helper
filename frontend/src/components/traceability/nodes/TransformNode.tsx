import React from 'react';
import { NodeProps } from 'reactflow';
import { Alert, Chip, Stack } from '@mui/material';
import { Transform as TransformIcon } from '@mui/icons-material';

import BaseNode from './BaseNode';

const TransformNode: React.FC<NodeProps> = ({ data, selected }) => {
  return (
    <BaseNode
      data={data}
      selected={selected}
      icon={<TransformIcon fontSize="small" />}
      color="secondary"
      category="Processor Node"
      hasInput={true}
      hasOutput={true}
    >
      <Stack spacing={1} sx={{ mt: 1 }}>
        <Chip label={`Type: ${data.config?.transform_type || 'passthrough'}`} size="small" />
        <Alert severity="info" sx={{ py: 0, '& .MuiAlert-message': { py: 0.25, fontSize: 12 } }}>
          Current backend mode: passthrough
        </Alert>
      </Stack>
    </BaseNode>
  );
};

export default TransformNode;
