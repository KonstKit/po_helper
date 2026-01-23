import type { PaginatedResponse, PaginationMeta } from './types';

type PaginationOptions = {
  skip?: number;
  limit?: number;
  legacyKey?: string;
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

const acceptAll = <T>(_value: unknown): _value is T => true;

const toArray = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);

const isPaginationMeta = (value: unknown): value is PaginationMeta => {
  if (!isRecord(value)) return false;
  return (
    typeof value.total === 'number' &&
    typeof value.page === 'number' &&
    typeof value.per_page === 'number' &&
    typeof value.total_pages === 'number' &&
    typeof value.has_next === 'boolean' &&
    typeof value.has_prev === 'boolean'
  );
};

const extractArray = <T>(
  payload: unknown,
  legacyKey?: string,
  isItem: (value: unknown) => value is T = acceptAll
): T[] => {
  if (Array.isArray(payload)) return toArray(payload).filter(isItem);
  if (!isRecord(payload)) return [];
  if (Array.isArray(payload.data)) return toArray(payload.data).filter(isItem);
  if (legacyKey && Array.isArray(payload[legacyKey])) {
    return toArray(payload[legacyKey]).filter(isItem);
  }
  if (Array.isArray(payload.items)) return toArray(payload.items).filter(isItem);
  return [];
};

const buildMeta = (opts: PaginationOptions | undefined, dataLength: number, totalFromPayload?: number): PaginationMeta => {
  const skip = opts?.skip ?? 0;
  const limit = opts?.limit ?? (dataLength || 1);
  const total = typeof totalFromPayload === 'number'
    ? totalFromPayload
    : Math.max(skip + dataLength, dataLength);
  const perPage = limit || Math.max(1, dataLength);
  const page = perPage > 0 ? Math.floor(skip / perPage) + 1 : 1;
  const totalPages = perPage > 0 ? Math.max(1, Math.ceil(total / perPage)) : 1;
  const hasNext = typeof totalFromPayload === 'number'
    ? skip + perPage < total
    : dataLength === perPage;
  const hasPrev = skip > 0;

  return {
    total,
    page,
    per_page: perPage,
    total_pages: totalPages,
    has_next: hasNext,
    has_prev: hasPrev,
  };
};

export const normalizePaginatedResponse = <T>(
  payload: unknown,
  opts?: PaginationOptions
): PaginatedResponse<T> => {
  const data = extractArray<T>(payload, opts?.legacyKey);

  if (isRecord(payload)) {
    if (isPaginationMeta(payload.meta)) {
      return { data, meta: payload.meta };
    }

    if (isRecord(payload.pagination)) {
      const p = payload.pagination;
      if (
        typeof p.total === 'number' &&
        typeof p.page === 'number' &&
        typeof p.limit === 'number'
      ) {
        return {
          data,
          meta: {
            total: p.total,
            page: p.page,
            per_page: p.limit,
            total_pages: typeof p.total_pages === 'number'
              ? p.total_pages
              : Math.max(1, Math.ceil(p.total / p.limit)),
            has_next: Boolean(p.has_next),
            has_prev: Boolean(p.has_prev),
          },
        };
      }
    }

    if (typeof payload.total === 'number') {
      return {
        data,
        meta: buildMeta(opts, data.length, payload.total),
      };
    }
  }

  return {
    data,
    meta: buildMeta(opts, data.length),
  };
};
