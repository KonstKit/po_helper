import React, { useEffect, useRef, useState } from 'react';
import { Box, Typography, Grid, TextField, Button, Divider, Alert, Switch, FormControlLabel, ToggleButtonGroup, ToggleButton, Chip } from '@mui/material';
import CircularProgressWithLabel from '../components/CircularProgressWithLabel';
import EmptyState from '../components/common/EmptyState';
import { DataGrid, GridColDef } from '@mui/x-data-grid';
import { ChevronRight as ChevronRightIcon, ExpandLess as ExpandLessIcon, MenuBook as MenuBookIcon } from '@mui/icons-material';
import {
  listConfluenceSpaces,
  listConfluencePages,
  listConfluencePagesLocal,
  getPrdRequirements,
  startConfluenceSyncStream,
  syncConfluence,
  getADR,
  getResearch,
  getSpaceTree,
  syncSubtree,
  type ConfluenceSyncStreamEvent,
  type ConfluenceSyncStreamHandle,
  type SpaceTreeNode,
} from '../services/api';
import { getErrorMessage } from '../utils/errorUtils';

/** Confluence space from API */
interface ConfluenceSpace {
  key: string;
  name?: string;
}

/** Confluence page with source tracking */
interface ConfluencePage {
  id: string;
  title: string;
  space?: string;
  version?: number;
  last_updated?: string;
  url?: string;
  _src?: 'remote' | 'db';
}

/** Parsed requirement row */
interface RequirementRow {
  id: string;
  description: string;
  priority: string;
}

const Knowledge = () => {
  const [spaceQuery, setSpaceQuery] = useState('');
  const [spaces, setSpaces] = useState<ConfluenceSpace[]>([]);
  const [spaceKey, setSpaceKey] = useState('');
  const [pageQuery, setPageQuery] = useState('PRD');
  const [pages, setPages] = useState<ConfluencePage[]>([]);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [requirements, setRequirements] = useState<RequirementRow[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState<{ loading: boolean; percent?: number; step?: string }>({ loading: false });
  const [lastSync, setLastSync] = useState<{synced: number; created: number; updated: number} | null>(null);
  const [autoSync, setAutoSync] = useState<boolean>(false);
  type KnowledgeSource = 'remote' | 'db' | 'both';
  const [source, setSource] = useState<KnowledgeSource>('remote');
  const [remoteStart, setRemoteStart] = useState(0);
  const [dbOffset, setDbOffset] = useState(0);
  const pageSize = 50;
  const [tree, setTree] = useState<SpaceTreeNode[] | null>(null);
  const [expanded, setExpanded] = useState<string[]>([]);
  const [plainView, setPlainView] = useState<boolean>(false);
  // Becomes true once the initial auto-load (or state restore) has settled, so
  // the empty-state never flashes before the first fetch has had a chance to run.
  const [initialLoadDone, setInitialLoadDone] = useState(false);
  const syncStreamRef = useRef<ConfluenceSyncStreamHandle | null>(null);
  // True once an earlier session's pages/tree have been rehydrated from storage,
  // so the auto-load effect can skip the initial fetch and avoid clobbering them.
  const restoredDataRef = useRef(false);
  // Guards the initial auto-load so it fires at most once per mount.
  const didAutoLoadRef = useRef(false);
  // Skips the persist effect's first run so it cannot write the initial (empty)
  // state over the just-restored snapshot before restore's updates apply (M6).
  const persistInitializedRef = useRef(false);

  // Restore state on mount
  useEffect(() => {
    try {
      let raw = sessionStorage.getItem('knowledge_state');
      if (!raw) {
        raw = localStorage.getItem('knowledge_state');
        if (raw) sessionStorage.setItem('knowledge_state', raw);
      }
      if (raw) {
        const s = JSON.parse(raw);
        if (s.spaceQuery !== undefined) setSpaceQuery(s.spaceQuery);
        if (Array.isArray(s.spaces)) setSpaces(s.spaces);
        if (s.spaceKey !== undefined) setSpaceKey(s.spaceKey);
        if (s.pageQuery !== undefined) setPageQuery(s.pageQuery);
        if (Array.isArray(s.pages)) setPages(s.pages);
        if (Array.isArray(s.requirements) || s.requirements === null) setRequirements(s.requirements);
        if (s.lastSync) setLastSync(s.lastSync);
        if (s.autoSync !== undefined) setAutoSync(!!s.autoSync);
        if (s.source) setSource(s.source);
        if (typeof s.remoteStart === 'number') setRemoteStart(s.remoteStart);
        if (typeof s.dbOffset === 'number') setDbOffset(s.dbOffset);
        if (Array.isArray(s.expanded)) setExpanded(s.expanded);
        if (Array.isArray(s.tree)) setTree(s.tree);
        // Remember whether the previous session already had data, so we don't
        // auto-fetch (and overwrite) on a return visit.
        if ((Array.isArray(s.pages) && s.pages.length > 0) || (Array.isArray(s.tree) && s.tree.length > 0)) {
          restoredDataRef.current = true;
        }
      }
    } catch (err) {
      console.warn('Failed to restore knowledge state', err);
    }
  }, []);

  // Persist state on change
  useEffect(() => {
    // Skip the first run: on mount the restore effect's setState()s are
    // scheduled but not yet applied, so this closure still holds the initial
    // (empty) state. Writing it would transiently clobber the just-restored
    // snapshot (it self-corrects on the next render, but risks loss on a fast
    // unmount and double-writes on every mount).
    if (!persistInitializedRef.current) {
      persistInitializedRef.current = true;
      return;
    }
    const snapshot = {
      spaceQuery,
      spaces,
      spaceKey,
      pageQuery,
      pages,
      requirements,
      lastSync,
      autoSync,
      source,
      remoteStart,
      dbOffset,
      expanded,
      tree,
    };
    try {
      const s = JSON.stringify(snapshot);
      sessionStorage.setItem('knowledge_state', s);
      localStorage.setItem('knowledge_state', s);
    } catch (err) {
      console.warn('Failed to persist knowledge state', err);
    }
  }, [spaceQuery, spaces, spaceKey, pageQuery, pages, requirements, lastSync, autoSync, source, remoteStart, dbOffset, expanded, tree]);

  useEffect(() => () => {
    syncStreamRef.current?.close();
    syncStreamRef.current = null;
  }, []);

  const loadSpaces = async () => {
    try {
      setLoading(true);
      setProgress({ loading: true, percent: 10, step: 'Loading Confluence spaces...' });
      const res = await listConfluenceSpaces(spaceQuery || undefined, 50);
      setSpaces(res.results || []);
      setMessage(null);
    } catch (e) {
      const detail = getErrorMessage(e, 'Failed to load spaces');
      setMessage({ type: 'error', text: detail });
    } finally {
      setLoading(false);
      setProgress({ loading: false, percent: 100, step: 'Ready' });
    }
  };

  const handleAutoSyncChange = (_: React.ChangeEvent<HTMLInputElement>, checked: boolean) => {
    setAutoSync(checked);
  };
  const handleSourceChange = (_: React.MouseEvent<HTMLElement>, value: string | null) => {
    if (value === 'remote' || value === 'db' || value === 'both') {
      setSource(value);
    }
  };

  const loadPages = async () => {
    try {
      setLoading(true);
      setProgress({ loading: true, percent: 5, step: 'Fetching remote pages...' });
      const results: ConfluencePage[] = [];
      if (source === 'remote' || source === 'both') {
        const r = await listConfluencePages({ space: spaceKey || undefined, q: pageQuery || undefined, limit: pageSize, start: 0 });
        results.push(...(r.results || []).map((it): ConfluencePage => ({...it, _src: 'remote'})));
        setRemoteStart(pageSize);
        if (autoSync) {
          try {
            setProgress({ loading: true, percent: 35, step: 'Syncing remote pages...' });
            await syncConfluence({
              space: spaceKey || undefined,
              q: pageQuery || undefined,
              limit: pageSize,
              full: true,
            });
          } catch (err) {
            console.warn('Auto-sync failed for remote pages', err);
          }
        }
      }
      if (source === 'db' || source === 'both') {
        setProgress({ loading: true, percent: 65, step: 'Loading local pages...' });
        const d = await listConfluencePagesLocal({ space: spaceKey || undefined, q: pageQuery || undefined, limit: pageSize, offset: 0 });
        results.push(...(d.results || []).map((it): ConfluencePage => ({...it, _src: 'db'})));
        setDbOffset(pageSize);
      }
      const seen = new Set<string>();
      const combined = results.filter((x) => (seen.has(x.id) ? false : (seen.add(x.id), true)));
      setPages(combined);
      setRequirements(null);
      setMessage(null);
    } catch (e) {
      const detail = getErrorMessage(e, 'Failed to load pages');
      setMessage({ type: 'error', text: detail });
    } finally {
      setLoading(false);
      setProgress({ loading: false, percent: 100, step: 'Ready' });
    }
  };

  // Auto-load the first page of results on mount (M6). Runs once and only when
  // nothing was restored from a previous session, so the table is populated
  // without a manual "Find Pages" click. Uses the same paginated loader as the
  // button (first page only) — deep tree/branch loading stays lazy/on-demand.
  useEffect(() => {
    if (didAutoLoadRef.current) return;
    didAutoLoadRef.current = true;
    // The restore effect (declared earlier) has already run for this mount; if
    // it rehydrated pages/tree, skip the auto-fetch to avoid overwriting them.
    if (restoredDataRef.current) {
      setInitialLoadDone(true);
      return;
    }
    void loadPages().finally(() => setInitialLoadDone(true));
    // Intentionally run once on mount; loadPages is stable for the initial fetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const doSync = async () => {
    try {
      setLoading(true);
      setProgress({ loading: true, percent: 5, step: 'Initializing sync...' });
      syncStreamRef.current?.close();

      let streamHandle: ConfluenceSyncStreamHandle | null = null;
      let streamClosed = false;
      let syncTimeout: ReturnType<typeof setTimeout> | null = null;

      const clearSyncTimeout = () => {
        if (syncTimeout) {
          clearTimeout(syncTimeout);
          syncTimeout = null;
        }
      };

      const closeSyncStream = () => {
        if (streamClosed) {
          return;
        }
        streamClosed = true;
        clearSyncTimeout();
        streamHandle?.close();
        if (syncStreamRef.current === streamHandle) {
          syncStreamRef.current = null;
        }
      };

      const resetTimeout = () => {
        clearSyncTimeout();
        syncTimeout = setTimeout(() => {
          console.warn('Sync stream timeout - closing connection');
          closeSyncStream();
          setMessage({ type: 'error', text: 'Sync timeout - please try again with smaller batches.' });
          setProgress({ loading: false, percent: 0, step: 'Timeout' });
          setLoading(false);
        }, 300000);
      };

      const handleSyncEvent = (data: ConfluenceSyncStreamEvent) => {
        resetTimeout();

        if (data.type === 'progress' || data.type === 'start') {
          setProgress({
            loading: true,
            percent: data.percent || 10,
            step: data.message || 'Syncing...',
          });

          if (data.synced !== undefined) {
            setLastSync({
              synced: data.synced,
              created: data.created || 0,
              updated: data.updated || 0,
            });
          }
          return;
        }

        if (data.type === 'complete') {
          closeSyncStream();
          setProgress({ loading: false, percent: 100, step: 'Complete' });
          setLastSync({
            synced: data.synced || 0,
            created: data.created || 0,
            updated: data.updated || 0,
          });
          setMessage({
            type: 'success',
            text: `Synced ${data.synced || 0} pages (created ${data.created || 0}, updated ${data.updated || 0}).`,
          });
          setLoading(false);
          return;
        }

        if (data.type === 'error') {
          closeSyncStream();
          setMessage({ type: 'error', text: data.message || 'Sync failed' });
          setProgress({ loading: false, percent: 0, step: 'Error' });
          setLoading(false);
        }
      };

      const handleStreamError = (error: Error) => {
        console.error('Confluence sync stream error:', error);
        closeSyncStream();
        setLoading(false);
        setProgress({ loading: false, percent: 0, step: 'Error' });
        setMessage({
          type: 'error',
          text: error.message || 'Sync stream failed.',
        });
      };

      streamHandle = startConfluenceSyncStream(
        {
          space: spaceKey || undefined,
          q: pageQuery || undefined,
          limit: 50,
          full: true,
        },
        {
          onEvent: handleSyncEvent,
          onError: handleStreamError,
        }
      );
      syncStreamRef.current = streamHandle;
      resetTimeout();

    } catch (e) {
      const detail = getErrorMessage(e, 'Sync failed');
      setMessage({ type: 'error', text: detail });
      setLoading(false);
      setProgress({ loading: false, percent: 0, step: 'Error' });
    }
  };

  const loadFromDb = async () => {
    try {
      setLoading(true);
      const res = await listConfluencePagesLocal({ space: spaceKey || undefined, q: pageQuery || undefined, limit: pageSize, offset: 0 });
      setDbOffset(pageSize);
      setPages((res.results || []).map((it): ConfluencePage => ({...it, _src: 'db'})));
      setMessage({ type: 'success', text: `Loaded ${res.count} pages from DB.` });
    } catch (e) {
      const detail = getErrorMessage(e, 'Failed to load from DB');
      setMessage({ type: 'error', text: detail });
    } finally {
      setLoading(false);
    }
  };

  const viewPrd = async (pageId: string) => {
    try {
      setLoading(true);
      setProgress({ loading: true, percent: 15, step: 'Extracting PRD requirements...' });
      const res = await getPrdRequirements(pageId);
      setRequirements(res.requirements || []);
      setMessage(null);
    } catch (e) {
      const detail = getErrorMessage(e, 'Failed to extract PRD requirements');
      setMessage({ type: 'error', text: detail });
    } finally {
      setLoading(false);
      setProgress({ loading: false, percent: 100, step: 'Ready' });
    }
  };

  const viewAdr = async (pageId: string) => {
    try {
      setLoading(true);
      setProgress({ loading: true, percent: 15, step: 'Extracting ADR...' });
      const res = await getADR(pageId);
      const rows = [
        { id: 'Status', description: res.status || '-', priority: '' },
        { id: 'Context', description: res.context || '-', priority: '' },
        { id: 'Decision', description: res.decision || '-', priority: '' },
        { id: 'Consequences', description: res.consequences || '-', priority: '' },
        { id: 'Alternatives', description: res.alternatives || '-', priority: '' },
      ];
      setRequirements(rows);
      setMessage(null);
    } catch (e) {
      const detail = getErrorMessage(e, 'Failed to parse ADR');
      setMessage({ type: 'error', text: detail });
    } finally {
      setLoading(false);
      setProgress({ loading: false, percent: 100, step: 'Ready' });
    }
  };

  const viewResearch = async (pageId: string) => {
    try {
      setLoading(true);
      setProgress({ loading: true, percent: 15, step: 'Collecting research insights...' });
      const res = await getResearch(pageId);
      const toRows = (label: string, items: string[]) => items.map((t) => ({ id: label, description: t, priority: '' }));
      const rows = [
        ...toRows('Positive', res.insights?.positive || []),
        ...toRows('Pain Points', res.insights?.pain_points || []),
        ...toRows('Feature Requests', res.insights?.feature_requests || []),
        ...toRows('Usability Issues', res.insights?.usability_issues || []),
      ];
      setRequirements(rows);
      setMessage(null);
    } catch (e) {
      const detail = getErrorMessage(e, 'Failed to parse Research');
      setMessage({ type: 'error', text: detail });
    } finally {
      setLoading(false);
      setProgress({ loading: false, percent: 100, step: 'Ready' });
    }
  };

  // Progress is rendered inline in the main component

  const loadMore = async () => {
    try {
      setLoading(true);
      const results: ConfluencePage[] = [];
      if (source === 'remote' || source === 'both') {
        const r = await listConfluencePages({ space: spaceKey || undefined, q: pageQuery || undefined, limit: pageSize, start: remoteStart });
        results.push(...(r.results || []).map((it): ConfluencePage => ({...it, _src: 'remote'})));
      }
      if (source === 'db' || source === 'both') {
        const d = await listConfluencePagesLocal({ space: spaceKey || undefined, q: pageQuery || undefined, limit: pageSize, offset: dbOffset });
        results.push(...(d.results || []).map((it): ConfluencePage => ({...it, _src: 'db'})));
      }
      const seen = new Set(pages.map((p) => p.id));
      const merged = [...pages, ...results.filter((x) => (seen.has(x.id) ? false : (seen.add(x.id), true)))];
      setPages(merged);
      if (source === 'remote' || source === 'both') setRemoteStart(remoteStart + pageSize);
      if (source === 'db' || source === 'both') setDbOffset(dbOffset + pageSize);
      if (autoSync && (source === 'remote' || source === 'both')) {
        try {
          await syncConfluence({
            space: spaceKey || undefined,
            q: pageQuery || undefined,
            limit: pageSize,
            start: remoteStart,
          });
        } catch (err) {
          console.warn('Auto-sync failed for additional pages', err);
        }
      }
    } catch (e) {
      const detail = getErrorMessage(e, 'Load more failed');
      setMessage({ type: 'error', text: detail });
    } finally {
      setLoading(false);
    }
  };

  const loadTree = async () => {
    try {
      const sk = (spaceKey || '').trim();
      if (!sk) {
        setMessage({ type: 'error', text: 'Please specify Space Key to load tree.' });
        return;
      }
      setLoading(true);
      const res = await getSpaceTree(sk, 200);
      const t = res.tree || [];
      setTree(t);
      // Expand roots by default so user sees content right away
      setExpanded(Array.isArray(t) ? t.map((n) => String(n.id)) : []);
      setMessage({ type: 'success', text: `Tree loaded: roots=${Array.isArray(t)?t.length:0}, total=${Array.isArray(t)?collectIds(t).length:0}` });
    } catch (e) {
      const detail = getErrorMessage(e, 'Failed to load space tree');
      setMessage({ type: 'error', text: detail });
    } finally {
      setLoading(false);
    }
  };

  const syncBranch = async (pageId: string) => {
    try {
      setLoading(true);
      const res = await syncSubtree(pageId, 50);
      setMessage({ type: 'success', text: `Synced subtree: ${res.synced} pages (created ${res.created}, updated ${res.updated}).` });
    } catch (e) {
      const detail = getErrorMessage(e, 'Failed to sync subtree');
      setMessage({ type: 'error', text: detail });
    } finally {
      setLoading(false);
    }
  };

  const collectIds = (nodes: SpaceTreeNode[]): string[] => {
    const out: string[] = [];
    const dfs = (arr: SpaceTreeNode[]) => {
      for (const n of arr) {
        if (n.id) out.push(String(n.id));
        if (Array.isArray(n.children) && n.children.length) dfs(n.children);
      }
    };
    dfs(nodes);
    return out;
  };

  const toggleNode = (id: string) => {
    setExpanded((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const renderCustomTree = (nodes: SpaceTreeNode[], depth = 0): React.ReactNode => (
    <Box>
      {nodes.map((n) => {
        const id = String(n.id);
        const hasChildren = Array.isArray(n.children) && n.children.length > 0;
        const isOpen = expanded.includes(id);
        return (
          <Box key={id} sx={{ pl: depth * 2, position: 'relative' }}>
            <Box display="flex" alignItems="center" sx={{ py: 0.5 }}>
              {hasChildren ? (
                <Box onClick={() => toggleNode(id)} sx={{ cursor: 'pointer', mr: 1, display: 'flex', alignItems: 'center' }}>
                  {isOpen ? <ExpandLessIcon fontSize="small" /> : <ChevronRightIcon fontSize="small" />}
                </Box>
              ) : (
                <Box sx={{ width: 24, mr: 1 }} />
              )}
              <Typography variant="body2" sx={{ mr: 1 }}>{n.title}</Typography>
              <Button size="small" onClick={() => syncBranch(id)}>Sync</Button>
            </Box>
            {hasChildren && isOpen && (
              <Box sx={{ ml: 1.5, pl: 1.5, borderLeft: '1px dashed rgba(0,0,0,0.2)' }}>
                {renderCustomTree(n.children || [], depth + 1)}
              </Box>
            )}
          </Box>
        );
      })}
    </Box>
  );

  const renderPlainList = (nodes: SpaceTreeNode[]): React.ReactNode => (
    <ul style={{ marginTop: 0 }}>
      {nodes.map((n) => (
        <li key={n.id}>
          <span>{n.title}</span>
          {Array.isArray(n.children) && n.children.length ? renderPlainList(n.children) : null}
        </li>
      ))}
    </ul>
  );

  const pageCols: GridColDef[] = [
    { field: 'id', headerName: 'ID', width: 120 },
    { field: 'title', headerName: 'Title', flex: 1, minWidth: 240 },
    { field: 'space', headerName: 'Space', width: 120 },
    { field: 'version', headerName: 'Ver', width: 80 },
    { field: 'last_updated', headerName: 'Last Updated', width: 200 },
    { field: '_src', headerName: 'Src', width: 80 },
    {
      field: 'url', headerName: 'Open', width: 100, renderCell: (params) => (
        typeof params.value === 'string'
          ? <a href={params.value} target="_blank" rel="noreferrer">Link</a>
          : null
      )
    },
    {
      field: 'actions', headerName: 'Actions', width: 240, renderCell: (params) => (
        <Box display="flex" gap={1}>
          <Button size="small" onClick={() => viewPrd(params.row.id)}>PRD</Button>
          <Button size="small" onClick={() => viewAdr(params.row.id)}>ADR</Button>
          <Button size="small" onClick={() => viewResearch(params.row.id)}>Research</Button>
        </Box>
      )
    },
  ];

  // Show empty state only after the initial load has settled and there is
  // genuinely nothing to show — never while a fetch is in flight (M4).
  const showEmptyState = initialLoadDone && pages.length === 0 && !loading && !tree;

  return (
    <Box>
      <Typography variant="h5" gutterBottom>Knowledge (Confluence)</Typography>
      {message && (<Alert severity={message.type} sx={{ mb: 2 }}>{message.text}</Alert>)}

      {showEmptyState && (
        <Box sx={{ my: 4 }}>
          <EmptyState
            icon={<MenuBookIcon />}
            title="No knowledge entries yet"
            description="Knowledge is populated by importing Confluence pages into the local database. Connect Confluence in Settings, then search and sync pages to bring in your team's PRDs, ADRs, and research notes."
            steps={[
              'Configure the Confluence connection in Settings',
              'Enter a Space Key and search for pages',
              'Click "Sync" to import pages into the local database',
            ]}
            actions={
              <Button variant="contained" onClick={() => { window.location.href = '/settings'; }}>
                Configure Confluence Integration
              </Button>
            }
          />
        </Box>
      )}
      <Grid container spacing={2} alignItems="center">
        <Grid item xs={12} md={6}>
          <TextField
            fullWidth
            label="Find Spaces (q)"
            value={spaceQuery}
            onChange={(e) => setSpaceQuery(e.target.value)}
            helperText="Search spaces by name/key"
          />
        </Grid>
        <Grid item xs={12} md={2}>
          <Button variant="outlined" onClick={loadSpaces} disabled={loading} fullWidth>Load Spaces</Button>
        </Grid>
      </Grid>
      <Box sx={{ mt: 1, mb: 2 }}>
        {spaces.length > 0 && (
          <>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
              Found {spaces.length} space{spaces.length === 1 ? '' : 's'}. Click a chip to fill Space Key.
            </Typography>
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
              {spaces.map((space) => (
                <Chip
                  key={space.key}
                  label={space.name ? `${space.key} - ${space.name}` : space.key}
                  variant={spaceKey === space.key ? 'filled' : 'outlined'}
                  color={spaceKey === space.key ? 'primary' : 'default'}
                  size="small"
                  onClick={() => setSpaceKey(space.key)}
                />
              ))}
            </Box>
          </>
        )}
      </Box>

      <Divider sx={{ my: 2 }} />

      <Grid container spacing={2} alignItems="center">
        <Grid item xs={12} md={3}>
          <TextField
            fullWidth
            label="Space Key"
            value={spaceKey}
            onChange={(e) => setSpaceKey(e.target.value)}
            helperText="Optional filter"
          />
        </Grid>
        <Grid item xs={12} md={5}>
          <TextField
            fullWidth
            label="Search Query (title/text)"
            value={pageQuery}
            onChange={(e) => setPageQuery(e.target.value)}
            helperText="Uses CQL when provided"
          />
        </Grid>
        <Grid item xs={12} md={2}>
          <Button variant="contained" onClick={loadPages} disabled={loading} fullWidth>Find Pages</Button>
        </Grid>
        <Grid item xs={12} md={2}>
          <Button variant="outlined" onClick={doSync} disabled={loading} fullWidth>Sync</Button>
        </Grid>
        <Grid item xs={12} md={2}>
          <Button variant="outlined" onClick={loadFromDb} disabled={loading} fullWidth>Load From DB</Button>
        </Grid>
        <Grid item xs={12} md={4}>
          <FormControlLabel
            control={<Switch checked={autoSync} onChange={handleAutoSyncChange} />}
            label="Auto-sync after search"
          />
        </Grid>
        <Grid item xs={12} md={8}>
          <ToggleButtonGroup
            size="small"
            exclusive
            value={source}
            onChange={handleSourceChange}
          >
            <ToggleButton value="remote">Remote</ToggleButton>
            <ToggleButton value="db">DB</ToggleButton>
            <ToggleButton value="both">Both</ToggleButton>
          </ToggleButtonGroup>
        </Grid>
      </Grid>

      {lastSync && (
        <Box sx={{ mt: 2 }}>
          <Typography variant="body2">Last Sync: synced {lastSync.synced}, created {lastSync.created}, updated {lastSync.updated}</Typography>
        </Box>
      )}

      {progress.loading && (
        <Box display="flex" justifyContent="center" my={2}>
          <CircularProgressWithLabel value={progress.percent} label={progress.step} size={80} />
        </Box>
      )}

      <Box sx={{ height: 420, mt: 1 }}>
        <DataGrid
          rows={pages}
          columns={pageCols}
          loading={false}
          getRowId={(r) => r.id}
          disableRowSelectionOnClick
        />
      </Box>

      <Box sx={{ mt: 2 }}>
        <Button variant="outlined" onClick={loadMore} disabled={loading}>Load More</Button>
      </Box>

      <Divider sx={{ my: 3 }} />
      <Typography variant="h6" gutterBottom>Space Tree</Typography>
      <Box display="flex" gap={2} mb={1}>
        <Button variant="outlined" onClick={loadTree} disabled={loading}>Load Tree</Button>
        <Button variant="outlined" onClick={() => tree && setExpanded(collectIds(tree))} disabled={loading || !tree || (Array.isArray(tree) && tree.length===0)}>Expand All</Button>
        <Button variant="outlined" onClick={() => setExpanded([])} disabled={loading || !tree || (Array.isArray(tree) && tree.length===0)}>Collapse All</Button>
        <Button variant="outlined" onClick={() => setPlainView((v)=>!v)} disabled={!tree || (Array.isArray(tree) && tree.length===0)}>
          {plainView ? 'Hide Plain View' : 'Show Plain View'}
        </Button>
      </Box>
      {tree && (
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
          Roots: {Array.isArray(tree) ? tree.length : 0}{tree && Array.isArray(tree) ? `, Total nodes: ${collectIds(tree).length}` : ''}
        </Typography>
      )}
      {Array.isArray(tree) && tree.length === 0 && (
        <Typography variant="body2" color="text.secondary">No pages found for this space.</Typography>
      )}
      {tree && tree.length>0 && !plainView && (
        <Box sx={{ maxHeight: 500, overflow: 'auto', border: '1px solid #eee', borderRadius: 1, p: 1 }}>
          {renderCustomTree(tree)}
        </Box>
      )}
      {tree && tree.length>0 && plainView && (
        <Box sx={{ maxHeight: 500, overflow: 'auto', border: '1px solid #eee', borderRadius: 1, p: 1 }}>
          {renderPlainList(tree)}
        </Box>
      )}

      {requirements && (
        <Box sx={{ mt: 3 }}>
          <Typography variant="h6" gutterBottom>PRD Requirements</Typography>
          {requirements.length === 0 ? (
            <Typography variant="body2">No requirements detected on this page.</Typography>
          ) : (
            <Box sx={{ border: '1px solid #eee', borderRadius: 1, p: 2 }}>
              <Grid container sx={{ fontWeight: 600, mb: 1 }}>
                <Grid item xs={3}>ID</Grid>
                <Grid item xs={7}>Description</Grid>
                <Grid item xs={2}>Priority</Grid>
              </Grid>
              {requirements.map((r, idx) => (
                <Grid container key={idx} sx={{ py: 0.5, borderTop: '1px solid #f5f5f5' }}>
                  <Grid item xs={3}>
                    <Typography variant="body2">{r.id}</Typography>
                  </Grid>
                  <Grid item xs={7}>
                    <Typography variant="body2">{r.description}</Typography>
                  </Grid>
                  <Grid item xs={2}>
                    <Typography variant="body2">{r.priority}</Typography>
                  </Grid>
                </Grid>
              ))}
            </Box>
          )}
        </Box>
      )}
    </Box>
  );
};

export default Knowledge;
