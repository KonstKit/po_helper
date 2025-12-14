import React from 'react';
import { NodeProps } from 'reactflow';
import { Chip } from '@mui/material';
import { BugReport as BugIcon } from '@mui/icons-material';
import BaseNode from './BaseNode';

const JiraIssueSourceNode: React.FC<NodeProps> = ({ data, selected }) => {
  return (
    <BaseNode
      data={data}
      selected={selected}
      icon={<BugIcon fontSize="small" />}
      color="success"
      category="Source Node"
      hasInput={true}
      hasOutput={true}
    >
      {data.filters?.project && (
        <Chip label={`Project: ${data.filters.project}`} size="small" sx={{ mt: 1, mr: 0.5 }} />
      )}
      {data.filters?.issue_type?.length > 0 && (
        <Chip label={`Types: ${data.filters.issue_type.join(', ')}`} size="small" sx={{ mt: 1, mr: 0.5 }} />
      )}
      {data.filters?.status?.length > 0 && (
        <Chip label={`Status: ${data.filters.status.join(', ')}`} size="small" sx={{ mt: 1 }} />
      )}
    </BaseNode>
  );
};

export default JiraIssueSourceNode;
