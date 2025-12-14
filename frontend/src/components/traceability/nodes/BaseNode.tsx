import React from 'react';
import { Handle, Position } from 'reactflow';
import { Box, Paper, Typography } from '@mui/material';

interface BaseNodeProps {
  data: any;
  selected: boolean;
  icon: React.ReactNode;
  color: string; // e.g., 'primary', 'success', 'info', 'secondary', 'warning'
  category: string; // 'Source Node', 'Processor Node', 'Action Node', 'Decision Node'
  children?: React.ReactNode;
  hasInput?: boolean;
  hasOutput?: boolean;
  outputHandles?: { id?: string; position?: number; color?: string }[];
}

const BaseNode: React.FC<BaseNodeProps> = ({
  data,
  selected,
  icon,
  color,
  category,
  children,
  hasInput = false,
  hasOutput = false,
  outputHandles,
}) => {
  return (
    <Paper
      elevation={selected ? 8 : 2}
      sx={{
        minWidth: 200,
        border: selected ? 3 : 1,
        borderColor: selected ? '#00ff00' : 'divider', // Ядовито-зеленый при выделении
        borderRadius: 1, // Закругленные углы
        overflow: 'hidden', // Чтобы внутренний контент не выходил за границы
      }}
    >
      {/* Header */}
      <Box
        sx={{
          bgcolor: `${color}.main`,
          color: `${color}.contrastText`,
          p: 1,
          display: 'flex',
          alignItems: 'center',
          gap: 1,
          // НЕ добавляем borderRadius сюда, т.к. overflow: hidden на Paper уже обрезает
        }}
      >
        {icon}
        <Typography variant="subtitle2">{data.label}</Typography>
      </Box>

      {/* Body */}
      <Box sx={{ p: 2 }}>
        <Typography variant="caption" color="text.secondary" display="block">
          {category}
        </Typography>
        {children}
      </Box>

      {/* Input Handle */}
      {hasInput && (
        <Handle
          type="target"
          position={Position.Left}
          style={{
            background: '#555',
            width: 12,
            height: 12,
            border: '2px solid white',
          }}
        />
      )}

      {/* Output Handles */}
      {hasOutput && !outputHandles && (
        <Handle
          type="source"
          position={Position.Right}
          style={{
            background: '#555',
            width: 12,
            height: 12,
            border: '2px solid white',
          }}
        />
      )}

      {/* Multiple Output Handles (for Decision node) */}
      {outputHandles &&
        outputHandles.map((handle, index) => (
          <Handle
            key={handle.id || index}
            type="source"
            position={Position.Right}
            id={handle.id}
            style={{
              background: handle.color || '#555',
              width: 12,
              height: 12,
              border: '2px solid white',
              top: handle.position !== undefined ? `${handle.position}%` : undefined,
            }}
          />
        ))}
    </Paper>
  );
};

export default BaseNode;
