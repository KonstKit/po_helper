import React, { useCallback, useEffect, useState } from 'react';
import {
  Box,
  Typography,
  TextField,
  Button,
  MenuItem,
  Alert,
  Chip,
  IconButton,
  Stack,
  Divider,
} from '@mui/material';
import { Delete as DeleteIcon, Save as SaveIcon } from '@mui/icons-material';
import { listProjects } from '../services/api/projects';
import {
  listConnectorConfigs,
  createConnectorConfig,
  deleteConnectorConfig,
} from '../services/api/traceability';
import type { ConnectorConfig } from '../services/api/traceability';
import type { Project } from '../services/api/types';
import { getErrorMessage } from '../utils/errorUtils';

/** Read the configured space key(s) out of a connector config's settings_json. */
const spaceKeyOf = (c: ConnectorConfig): string => {
  const s = (c.settings_json || {}) as Record<string, unknown>;
  const raw = s.space_key ?? s.space ?? s.spaceKey;
  if (Array.isArray(raw)) {
    return raw.map((v) => String(v)).join(', ');
  }
  return typeof raw === 'string' ? raw : '';
};

type MessageState = { type: 'success' | 'error'; text: string };

/**
 * Confluence space mapping (connector-config) manager.
 *
 * Traceability repair resolves a project's Confluence space key from its
 * connector override, falling back to the project's Jira key. When a project's
 * Confluence space key differs from its Jira key (e.g. space "SMH" for a "WAB"
 * project) repair cannot import that project's Confluence pages until a mapping
 * is configured. The backend exposes `/connector-configs` for this but had no
 * UI — this panel fills that gap.
 */
export function ConfluenceSpaceMapping(): React.ReactElement {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<number | ''>('');
  const [configs, setConfigs] = useState<ConnectorConfig[]>([]);
  const [spaceKey, setSpaceKey] = useState('');
  const [message, setMessage] = useState<MessageState | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const res = await listProjects({ limit: 200 });
        setProjects(res.data || []);
      } catch (e) {
        setMessage({ type: 'error', text: getErrorMessage(e, 'Failed to load projects') });
      }
    })();
  }, []);

  const loadConfigs = useCallback(async (pid: number) => {
    try {
      const res = await listConnectorConfigs(pid, 'confluence');
      setConfigs(res);
    } catch (e) {
      setMessage({ type: 'error', text: getErrorMessage(e, 'Failed to load mappings') });
    }
  }, []);

  useEffect(() => {
    if (typeof projectId === 'number') {
      void loadConfigs(projectId);
    } else {
      setConfigs([]);
    }
  }, [projectId, loadConfigs]);

  const handleSave = async () => {
    if (typeof projectId !== 'number' || !spaceKey.trim()) return;
    const key = spaceKey.trim();
    setLoading(true);
    try {
      await createConnectorConfig({
        project_id: projectId,
        provider: 'confluence',
        is_enabled: true,
        settings_json: { space_key: key },
      });
      setSpaceKey('');
      setMessage({ type: 'success', text: `Mapped project to Confluence space "${key}".` });
      await loadConfigs(projectId);
    } catch (e) {
      setMessage({ type: 'error', text: getErrorMessage(e, 'Failed to save mapping') });
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (id: number) => {
    setLoading(true);
    try {
      await deleteConnectorConfig(id);
      if (typeof projectId === 'number') {
        await loadConfigs(projectId);
      }
    } catch (e) {
      setMessage({ type: 'error', text: getErrorMessage(e, 'Failed to delete mapping') });
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box>
      <Typography variant="h6" gutterBottom>
        Confluence Space Mapping
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Map a project to its Confluence space key(s) so traceability repair can import that
        project&apos;s Confluence pages. Required when the Confluence space key differs from the
        project&apos;s Jira key (otherwise repair falls back to the Jira key and finds no pages).
      </Typography>

      {message && (
        <Alert severity={message.type} onClose={() => setMessage(null)} sx={{ mb: 2 }}>
          {message.text}
        </Alert>
      )}

      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ mb: 2 }} alignItems="flex-start">
        <TextField
          select
          label="Project"
          value={projectId === '' ? '' : String(projectId)}
          onChange={(e) => setProjectId(e.target.value === '' ? '' : Number(e.target.value))}
          sx={{ minWidth: 260 }}
        >
          {projects.map((p) => (
            <MenuItem key={p.id} value={String(p.id)}>
              {p.name} ({p.jira_key})
            </MenuItem>
          ))}
        </TextField>
        <TextField
          label="Confluence Space Key"
          value={spaceKey}
          onChange={(e) => setSpaceKey(e.target.value)}
          placeholder="e.g. SMH"
          helperText="The Confluence space key (not the space name)"
          sx={{ minWidth: 220 }}
        />
        <Button
          variant="contained"
          startIcon={<SaveIcon />}
          onClick={handleSave}
          disabled={loading || typeof projectId !== 'number' || !spaceKey.trim()}
        >
          Save mapping
        </Button>
      </Stack>

      <Divider sx={{ my: 2 }} />

      <Typography variant="subtitle2" gutterBottom>
        Existing Confluence mappings
      </Typography>
      {configs.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          {typeof projectId === 'number'
            ? 'No Confluence space mappings for this project yet.'
            : 'Select a project to view its Confluence space mappings.'}
        </Typography>
      ) : (
        <Stack spacing={1}>
          {configs.map((c) => (
            <Box key={c.id} display="flex" alignItems="center" gap={1}>
              <Chip
                label={`space: ${spaceKeyOf(c) || '(none)'}`}
                color={c.is_enabled ? 'primary' : 'default'}
                size="small"
              />
              <Typography variant="caption" color="text.secondary">
                {c.is_enabled ? 'enabled' : 'disabled'}
              </Typography>
              <IconButton
                size="small"
                aria-label="delete mapping"
                onClick={() => handleDelete(c.id)}
                disabled={loading}
              >
                <DeleteIcon fontSize="small" />
              </IconButton>
            </Box>
          ))}
        </Stack>
      )}
    </Box>
  );
}

export default ConfluenceSpaceMapping;
