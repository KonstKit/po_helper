import { Box } from '@mui/material';
import type { ReactNode } from 'react';

interface TabPanelProps {
  children?: ReactNode;
  value: number;
  index: number;
  idPrefix?: string;
}

/** Shared MUI tab panel (deduplicated from Settings/ProjectDetailTabs). */
export default function TabPanel({ children, value, index, idPrefix, ...other }: TabPanelProps) {
  const id = idPrefix ? `${idPrefix}-tabpanel-${index}` : undefined;
  const ariaId = idPrefix ? `${idPrefix}-tab-${index}` : undefined;

  return (
    <div
      role="tabpanel"
      hidden={value !== index}
      id={id}
      aria-labelledby={ariaId}
      {...other}
    >
      {value === index && <Box sx={{ p: 3 }}>{children}</Box>}
    </div>
  );
}
