import type { TraceabilityBackfillResult, TraceabilityMatrixSummary } from '../../services/api';

// Pure helpers extracted from pages/Traceability.tsx (decomposition).

export type CoreLinkType = 'implements' | 'tests' | 'deploys' | 'derives_from';
export const CORE_LINK_TYPES: CoreLinkType[] = ['implements', 'tests', 'deploys', 'derives_from'];
export const CORE_LINK_TYPES_SET = new Set<string>(CORE_LINK_TYPES);

export const parseProjectId = (value: string): number | 'all' => {
  if (value >= 'all') {
    return 'all';
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 'all';
};

export const buildRepairMessage = (result: TraceabilityBackfillResult): string => {
  const details: string[] = [];

  if (result.sources.jira) {
    details.push(`Jira ${result.sources.jira.created} created / ${result.sources.jira.updated} updated`);
  }
  if (result.sources.confluence) {
    details.push(
      `Confluence ${result.sources.confluence.created} created / ${result.sources.confluence.updated} updated`
    );
  }
  if (result.sources.git) {
    const repositories = result.sources.git.repositories ?? [];
    details.push(
      repositories.length > 0
        ? `Git synced ${repositories.length} ${repositories.length === 1 ? 'repository' : 'repositories'}`
        : 'Git checked with no repository changes'
    );
  }

  const summary = `Traceability repair complete: created ${result.created}, updated ${result.updated}.`;
  return details.length > 0 ? `${summary} ${details.join(' • ')}.` : summary;
};

export interface LinkTypeBreakdown {
  key: string;
  totalLinks: number;
  artifactCount: number;
  coverageRatio: number;
  isCore: boolean;
}

export interface TypeRow {
  type: string;
  total: number;
  sharePct: number;
  linked: number;
  unlinked: number;
  coveragePct: number;
  avgLinks: number | null;
  totalLinks: number | null;
  linkTypes: LinkTypeBreakdown[];
  hasCoverageGap: boolean;
  coreMissingCount: number;
}

export const buildTypeRows = (matrix: TraceabilityMatrixSummary | null): TypeRow[] => {
  if (!matrix) return [];
  const keys = new Set<string>();
  Object.keys(matrix.by_type || {}).forEach(key => keys.add(key));
  Object.keys(matrix.per_type || {}).forEach(key => keys.add(key));
  return Array.from(keys)
    .map<TypeRow>(type => {
      const stats = matrix.per_type?.[type];
      const total = stats?.total ?? matrix.by_type?.[type] ?? 0;
      const linked = stats?.linked ?? 0;
      const unlinked = stats?.unlinked ?? Math.max(total - linked, 0);
      const coveragePct = stats?.coverage_pct ?? (total > 0 ? (linked / total) * 100 : 0);
      const avgLinks = stats?.avg_links_per_artifact ?? null;
      const totalLinks = stats?.link_count ?? null;
      const sharePct = matrix.total > 0 ? (total / matrix.total) * 100 : 0;

      const linkTypeCounts = stats?.link_type_counts ?? {};
      const linkTypeArtifactCounts = stats?.link_type_artifact_counts ?? {};
      const dynamicTypes = Object.keys(linkTypeCounts).filter(linkType => !CORE_LINK_TYPES_SET.has(linkType));
      const orderedTypes = [...CORE_LINK_TYPES, ...dynamicTypes];
      const seen = new Set<string>();
      const linkTypes = orderedTypes.reduce<LinkTypeBreakdown[]>((acc, linkType) => {
        const key = String(linkType);
        if (seen.has(key)) {
          return acc;
        }
        seen.add(key);
        const totalForType = linkTypeCounts[key] ?? 0;
        if (!CORE_LINK_TYPES_SET.has(key) && totalForType === 0) {
          return acc;
        }
        const artifactCountForType = linkTypeArtifactCounts[key] ?? 0;
        const coverageRatio = total > 0 ? artifactCountForType / total : 0;
        acc.push({
          key,
          totalLinks: totalForType,
          artifactCount: artifactCountForType,
          coverageRatio,
          isCore: CORE_LINK_TYPES_SET.has(key),
        });
        return acc;
      }, []);

      const coreMissingCount = linkTypes.filter(item => item.isCore && item.totalLinks === 0).length;
      const hasCoverageGap = coreMissingCount > 0;

      return {
        type,
        total,
        sharePct,
        linked,
        unlinked,
        coveragePct,
        avgLinks,
        totalLinks,
        linkTypes,
        hasCoverageGap,
        coreMissingCount,
      };
    })
    .sort((a, b) => b.sharePct - a.sharePct);
};

export const coverageChipColor = (pct: number): 'success' | 'warning' | 'error' => {
  if (pct >= 80) return 'success';
  if (pct >= 50) return 'warning';
  return 'error';
};

export const formatConfidence = (value?: number | null): string => {
  if (value === undefined || value === null) return 'N/A';
  const pct = Math.round(value * 100);
  return `${pct}%`;
};
