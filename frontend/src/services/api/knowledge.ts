/**
 * Knowledge APIs - Confluence spaces, pages, PRD requirements, ADRs, research.
 */
import api from './client';

// =============================================================================
// Confluence Spaces
// =============================================================================

export interface ConfluenceSpace {
  id: string;
  key: string;
  name: string;
  url?: string;
}

export interface ConfluenceSpacesResponse {
  count: number;
  results: ConfluenceSpace[];
}

export const listConfluenceSpaces = async (
  q?: string,
  limit = 50
): Promise<ConfluenceSpacesResponse> => {
  const params: Record<string, unknown> = { limit };
  if (q) params.q = q;

  const { data } = await api.get('/v1/confluence/spaces', { params });
  return data as ConfluenceSpacesResponse;
};

// =============================================================================
// Confluence Pages
// =============================================================================

export interface ConfluencePage {
  id: string;
  title: string;
  space?: string;
  url?: string;
  version?: number;
  last_updated?: string;
}

export interface ConfluencePagesResponse {
  count: number;
  results: ConfluencePage[];
}

export const listConfluencePages = async (opts?: {
  space?: string;
  q?: string;
  limit?: number;
  start?: number;
}): Promise<ConfluencePagesResponse> => {
  const params: Record<string, unknown> = {};
  if (opts?.space) params.space = opts.space;
  if (opts?.q) params.q = opts.q;
  params.limit = opts?.limit ?? 50;
  if (opts?.start !== undefined) params.start = opts.start;

  const { data } = await api.get('/v1/confluence/pages', { params });
  return data as ConfluencePagesResponse;
};

export const listConfluencePagesLocal = async (opts?: {
  space?: string;
  q?: string;
  limit?: number;
  offset?: number;
}): Promise<ConfluencePagesResponse> => {
  const params: Record<string, unknown> = {};
  if (opts?.space) params.space = opts.space;
  if (opts?.q) params.q = opts.q;
  params.limit = opts?.limit ?? 50;
  if (opts?.offset !== undefined) params.offset = opts.offset;

  const { data } = await api.get('/v1/confluence/local/pages', { params });
  return data as ConfluencePagesResponse;
};

// =============================================================================
// Single Page Content
// =============================================================================

export interface ConfluencePageDetail {
  id: string;
  title: string;
  url?: string;
  html?: string;
  labels?: unknown;
  version?: number;
}

export const getConfluencePage = async (pageId: string): Promise<ConfluencePageDetail> => {
  const { data } = await api.get(`/v1/confluence/pages/${pageId}`);
  return data as ConfluencePageDetail;
};

// =============================================================================
// PRD Requirements
// =============================================================================

export interface PrdRequirement {
  id: string;
  description: string;
  priority: string;
}

export interface PrdRequirementsResponse {
  count: number;
  requirements: PrdRequirement[];
}

export const getPrdRequirements = async (pageId: string): Promise<PrdRequirementsResponse> => {
  const { data } = await api.get(`/v1/confluence/prd/${pageId}/requirements`);
  return data as PrdRequirementsResponse;
};

// =============================================================================
// Confluence Sync
// =============================================================================

export interface ConfluenceSyncResult {
  synced: number;
  created: number;
  updated: number;
}

export interface ConfluenceSyncStreamEvent extends Partial<ConfluenceSyncResult> {
  type: 'start' | 'progress' | 'complete' | 'error';
  percent?: number;
  message?: string;
}

export interface ConfluenceSyncStreamHandle {
  mode: 'fetch' | 'eventsource';
  close: () => void;
}

const resolveApiBaseForStreaming = (): string => {
  const configured = (import.meta.env.VITE_API_URL || '').trim();
  if (configured) {
    return configured.replace(/\/+$/, '');
  }
  if (typeof window !== 'undefined' && window.location?.origin) {
    return window.location.origin;
  }
  return '';
};

const buildApiV1StreamingUrl = (endpoint: string, params: URLSearchParams): string => {
  const base = resolveApiBaseForStreaming();
  const normalizedEndpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
  if (!base) {
    return `/api/v1${normalizedEndpoint}?${params.toString()}`;
  }
  const apiPrefix = base.endsWith('/api') ? '/v1' : '/api/v1';
  return `${base}${apiPrefix}${normalizedEndpoint}?${params.toString()}`;
};

const isUnauthenticatedDemoStreamEnabled = (): boolean =>
  String(import.meta.env.VITE_ALLOW_UNAUTHENTICATED_DEMO_API || '').toLowerCase() === 'true';

const parseSyncStreamEvent = (rawEvent: string): ConfluenceSyncStreamEvent | null => {
  const dataLines = rawEvent
    .split('\n')
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trimStart());

  if (dataLines.length === 0) {
    return null;
  }

  const payload = JSON.parse(dataLines.join('\n'));
  if (!payload || typeof payload !== 'object') {
    return null;
  }

  return payload as ConfluenceSyncStreamEvent;
};

const parseErrorDetail = (payload: unknown, fallback: string): Error => {
  if (payload && typeof payload === 'object') {
    const detail = (payload as { detail?: unknown }).detail;
    if (typeof detail === 'string' && detail.trim()) {
      return new Error(detail);
    }
  }
  return new Error(fallback);
};

const consumeEventStream = async (
  response: Response,
  onEvent: (event: ConfluenceSyncStreamEvent) => void,
): Promise<void> => {
  if (!response.ok) {
    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    throw parseErrorDetail(payload, `Sync request failed with status ${response.status}`);
  }

  if (!response.body) {
    throw new Error('Streaming response body is not available.');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    buffer = buffer.replace(/\r\n/g, '\n').replace(/\r/g, '\n');

    let boundaryIndex = buffer.indexOf('\n\n');
    while (boundaryIndex !== -1) {
      const rawEvent = buffer.slice(0, boundaryIndex).trim();
      buffer = buffer.slice(boundaryIndex + 2);
      boundaryIndex = buffer.indexOf('\n\n');

      if (!rawEvent || rawEvent.startsWith(':')) {
        continue;
      }

      const event = parseSyncStreamEvent(rawEvent);
      if (event) {
        onEvent(event);
      }
    }

    if (done) {
      break;
    }
  }
};

export const syncConfluence = async (opts?: {
  space?: string;
  q?: string;
  limit?: number;
  start?: number;
  full?: boolean;
}): Promise<ConfluenceSyncResult> => {
  const params: Record<string, unknown> = {};
  if (opts?.space) params.space = opts.space;
  if (opts?.q) params.q = opts.q;
  params.limit = opts?.limit ?? 50;
  if (opts?.full) params.full = 'true';
  if (opts?.start !== undefined) params.start = opts.start;

  const { data } = await api.post('/v1/confluence/sync', undefined, {
    params,
    timeout: 120000,
  });
  return data as ConfluenceSyncResult;
};

export const startConfluenceSyncStream = (
  opts: {
    space?: string;
    q?: string;
    limit?: number;
    start?: number;
    full?: boolean;
  },
  handlers: {
    onEvent: (event: ConfluenceSyncStreamEvent) => void;
    onError: (error: Error) => void;
  }
): ConfluenceSyncStreamHandle => {
  const params = new URLSearchParams();
  if (opts.space) params.set('space', opts.space);
  if (opts.q) params.set('q', opts.q);
  params.set('limit', String(opts.limit ?? 50));
  params.set('full', opts.full === false ? 'false' : 'true');
  if (opts.start !== undefined) params.set('start', String(opts.start));

  const url = buildApiV1StreamingUrl('/confluence/sync-sse', params);
  const attachDemoEventSource = () => {
    const eventSource = new EventSource(url);
    eventSource.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data) as ConfluenceSyncStreamEvent;
        handlers.onEvent(parsed);
      } catch {
        handlers.onError(new Error('Received invalid sync stream payload.'));
      }
    };
    eventSource.onerror = () => {
      eventSource.close();
      handlers.onError(new Error('SSE connection failed.'));
    };
    return {
      mode: 'eventsource',
      close: () => eventSource.close(),
    };
  };

  // JWT storage migration M2: the httpOnly cookie authenticates the
  // same-origin fetch automatically; no bearer header. Unauthenticated
  // demo deployments keep the EventSource path.
  const controller = new AbortController();
  let handle: ConfluenceSyncStreamHandle = {
    mode: 'fetch',
    close: () => controller.abort(),
  };

  void (async () => {
    try {
      const response = await fetch(url, {
        method: 'GET',
        headers: {
          Accept: 'text/event-stream',
        },
        credentials: 'include',
        signal: controller.signal,
      });
      if ((response.status === 401 || response.status === 403) && isUnauthenticatedDemoStreamEnabled()) {
        controller.abort();
        Object.assign(handle, attachDemoEventSource());
        return;
      }
      await consumeEventStream(response, handlers.onEvent);
    } catch (error) {
      if (controller.signal.aborted) {
        return;
      }
      handlers.onError(error instanceof Error ? error : new Error('Confluence sync failed.'));
    }
  })();

  return handle;
};

// =============================================================================
// Space Tree
// =============================================================================

export interface SpaceTreeNode {
  id: string;
  title: string;
  children?: SpaceTreeNode[];
}

export interface SpaceTreeResponse {
  count: number;
  tree: SpaceTreeNode[];
}

export const getSpaceTree = async (
  spaceKey: string,
  limit = 100,
  maxPages?: number
): Promise<SpaceTreeResponse> => {
  const params = new URLSearchParams({ limit: String(limit) });
  if (typeof maxPages === 'number') params.set('max_pages', String(maxPages));

  const { data } = await api.get(
    `/v1/confluence/spaces/${encodeURIComponent(spaceKey)}/tree?${params}`
  );
  return data as SpaceTreeResponse;
};

export const syncSubtree = async (
  pageId: string,
  limit = 50
): Promise<ConfluenceSyncResult> => {
  const params = new URLSearchParams({ limit: String(limit) });

  const { data } = await api.post(
    `/v1/confluence/subtree/${encodeURIComponent(pageId)}/sync?${params.toString()}`,
    undefined,
    { timeout: 120000 }
  );
  return data as ConfluenceSyncResult;
};

// =============================================================================
// ADR (Architecture Decision Records)
// =============================================================================

export interface ADRResponse {
  id: string;
  title: string;
  status?: string | null;
  context?: string;
  decision?: string;
  consequences?: string;
  alternatives?: string;
}

export const getADR = async (pageId: string): Promise<ADRResponse> => {
  const { data } = await api.get(`/v1/confluence/adr/${pageId}`);
  return data as ADRResponse;
};

// =============================================================================
// Research
// =============================================================================

export interface ResearchResponse {
  id: string;
  title: string;
  insights: Record<string, string[]>;
}

export const getResearch = async (pageId: string): Promise<ResearchResponse> => {
  const { data } = await api.get(`/v1/confluence/research/${pageId}`);
  return data as ResearchResponse;
};
