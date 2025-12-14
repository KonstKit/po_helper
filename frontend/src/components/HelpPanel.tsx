import React, { useState } from 'react';
import {
  Box,
  Paper,
  Typography,
  Collapse,
  IconButton,
  Button,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  Link,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import PlayCircleOutlineIcon from '@mui/icons-material/PlayCircleOutline';
import ArticleOutlinedIcon from '@mui/icons-material/ArticleOutlined';

interface HelpStep {
  text: string;
  icon?: React.ReactNode;
}

interface HelpPanelProps {
  title: string;
  description?: string;
  steps?: HelpStep[];
  videoUrl?: string;
  docsUrl?: string;
  defaultExpanded?: boolean;
  variant?: 'info' | 'guide' | 'warning';
}

const HelpPanelComponent: React.FC<HelpPanelProps> = ({
  title,
  description,
  steps,
  videoUrl,
  docsUrl,
  defaultExpanded = false,
  variant = 'info',
}) => {
  const [expanded, setExpanded] = useState(defaultExpanded);

  const getVariantColors = () => {
    switch (variant) {
      case 'guide':
        return {
          bg: 'primary.light',
          iconColor: 'primary.main',
          icon: <InfoOutlinedIcon />,
        };
      case 'warning':
        return {
          bg: 'warning.light',
          iconColor: 'warning.main',
          icon: <InfoOutlinedIcon />,
        };
      case 'info':
      default:
        return {
          bg: 'info.light',
          iconColor: 'info.main',
          icon: <InfoOutlinedIcon />,
        };
    }
  };

  const colors = getVariantColors();

  return (
    <Paper
      sx={{
        bgcolor: colors.bg,
        color: 'primary.contrastText',
        border: '1px solid',
        borderColor: `${colors.iconColor}`,
        borderRadius: 2,
        overflow: 'hidden',
        mb: 2,
      }}
    >
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          p: 2,
          cursor: 'pointer',
        }}
        onClick={() => setExpanded(!expanded)}
      >
        <Box display="flex" alignItems="center" gap={1}>
          <Box sx={{ color: 'primary.contrastText' }}>{colors.icon}</Box>
          <Typography variant="subtitle1" fontWeight={600} color="primary.contrastText">
            {title}
          </Typography>
        </Box>
        <IconButton size="small" sx={{ color: 'primary.contrastText' }}>
          {expanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
        </IconButton>
      </Box>

      <Collapse in={expanded}>
        <Box sx={{ px: 2, pb: 2, pt: 0 }}>
          {description && (
            <Typography variant="body2" color="rgba(255, 255, 255, 0.9)" paragraph>
              {description}
            </Typography>
          )}

          {steps && steps.length > 0 && (
            <List dense>
              {steps.map((step, idx) => (
                <ListItem key={idx} sx={{ pl: 0 }}>
                  <ListItemIcon sx={{ minWidth: 36, color: 'rgba(255, 255, 255, 0.7)' }}>
                    {step.icon || (
                      <CheckCircleOutlineIcon fontSize="small" />
                    )}
                  </ListItemIcon>
                  <ListItemText
                    primary={step.text}
                    primaryTypographyProps={{
                      variant: 'body2',
                      color: 'rgba(255, 255, 255, 0.9)',
                    }}
                  />
                </ListItem>
              ))}
            </List>
          )}

          {(videoUrl || docsUrl) && (
            <Box display="flex" gap={1} mt={2}>
              {videoUrl && (
                <Button
                  size="small"
                  variant="outlined"
                  startIcon={<PlayCircleOutlineIcon />}
                  href={videoUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  sx={{ textTransform: 'none' }}
                >
                  Watch Video
                </Button>
              )}
              {docsUrl && (
                <Button
                  size="small"
                  variant="outlined"
                  startIcon={<ArticleOutlinedIcon />}
                  href={docsUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  sx={{ textTransform: 'none' }}
                >
                  Read Docs
                </Button>
              )}
            </Box>
          )}
        </Box>
      </Collapse>
    </Paper>
  );
};

HelpPanelComponent.displayName = 'HelpPanel';

export const HelpPanel = React.memo(HelpPanelComponent);
