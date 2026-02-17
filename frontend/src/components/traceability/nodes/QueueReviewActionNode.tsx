import React from 'react';
import { NodeProps } from 'reactflow';
import { Alert, Chip, Stack } from '@mui/material';
import { RateReview as QueueReviewIcon } from '@mui/icons-material';

import BaseNode from './BaseNode';

const QueueReviewActionNode: React.FC<NodeProps> = ({ data, selected }) => {
  return (
    <BaseNode
      data={data}
      selected={selected}
      icon={<QueueReviewIcon fontSize="small" />}
      color="warning"
      category="Action Node"
      hasInput={true}
    >
      <Stack spacing={1} sx={{ mt: 1 }}>
        {data.config?.priority && <Chip label={`Priority: ${data.config.priority}`} size="small" />}
        {data.config?.reason && <Chip label={`Reason: ${data.config.reason}`} size="small" />}
        <Alert severity="warning" sx={{ py: 0, '& .MuiAlert-message': { py: 0.25, fontSize: 12 } }}>
          Backend action is warning-driven
        </Alert>
      </Stack>
    </BaseNode>
  );
};

export default QueueReviewActionNode;
