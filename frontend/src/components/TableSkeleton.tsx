import React from 'react';
import {
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Skeleton,
  Paper,
} from '@mui/material';

interface TableSkeletonProps {
  rows?: number;
  columns?: number;
  showHeader?: boolean;
  columnWidths?: (number | string)[];
}

const TableSkeletonComponent: React.FC<TableSkeletonProps> = ({
  rows = 10,
  columns = 5,
  showHeader = true,
  columnWidths = [],
}) => {
  return (
    <TableContainer component={Paper}>
      <Table>
        {showHeader && (
          <TableHead>
            <TableRow>
              {Array.from({ length: columns }).map((_, idx) => (
                <TableCell key={idx}>
                  <Skeleton
                    variant="text"
                    width={columnWidths[idx] || '80%'}
                    height={24}
                  />
                </TableCell>
              ))}
            </TableRow>
          </TableHead>
        )}
        <TableBody>
          {Array.from({ length: rows }).map((_, rowIdx) => (
            <TableRow key={rowIdx}>
              {Array.from({ length: columns }).map((_, colIdx) => (
                <TableCell key={colIdx}>
                  <Skeleton
                    variant="text"
                    width={columnWidths[colIdx] || '90%'}
                    height={20}
                  />
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
};

TableSkeletonComponent.displayName = 'TableSkeleton';

export const TableSkeleton = React.memo(TableSkeletonComponent);
