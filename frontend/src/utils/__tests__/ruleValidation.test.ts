import { describe, expect, it } from 'vitest';
import { Edge, Node } from 'reactflow';
import { SUPPORTED_TRANSFORM_TYPES, validateRule } from '../ruleValidation';

const buildFlow = (transformConfig: Record<string, unknown>): { nodes: Node[]; edges: Edge[] } => ({
  nodes: [
    {
      id: 'src',
      type: 'manualSource',
      position: { x: 0, y: 0 },
      data: { label: 'Source', config: { artifact_ids: [1] } },
    } as Node,
    {
      id: 'tx',
      type: 'transformNode',
      position: { x: 100, y: 0 },
      data: { label: 'Transform', config: transformConfig },
    } as Node,
    {
      id: 'act',
      type: 'createLinkAction',
      position: { x: 200, y: 0 },
      data: { label: 'Link', config: { link_type: 'relates_to' } },
    } as Node,
  ],
  edges: [
    { id: 'e1', source: 'src', target: 'tx' } as Edge,
    { id: 'e2', source: 'tx', target: 'act' } as Edge,
  ],
});

describe('ruleValidation transform contract', () => {
  it('exposes only passthrough as a supported transform type', () => {
    expect(Array.from(SUPPORTED_TRANSFORM_TYPES)).toEqual(['passthrough']);
  });

  it('accepts passthrough', () => {
    const { nodes, edges } = buildFlow({ transform_type: 'passthrough' });
    const result = validateRule(nodes, edges);
    expect(result.errors.filter((e) => e.message.includes('Transform node'))).toEqual([]);
  });

  it('accepts a transform node without an explicit transform_type', () => {
    const { nodes, edges } = buildFlow({});
    const result = validateRule(nodes, edges);
    expect(result.errors.filter((e) => e.message.includes('Transform node'))).toEqual([]);
  });

  it('emits a warning (not an error) for unsupported string transform_type', () => {
    // Frontend validation is advisory; the backend is the authoritative
    // gate (strict mode rejects on save/execute, non-strict passes through).
    // Hard-failing on the client would let the UI disable "Execute Rule"
    // even when the backend would allow the run.
    const { nodes, edges } = buildFlow({ transform_type: 'uppercase' });
    const result = validateRule(nodes, edges);
    const transformErrors = result.errors.filter((e) => e.message.includes('Transform node'));
    const transformWarnings = result.warnings.filter((w) => w.message.includes('Transform node'));
    expect(transformErrors).toEqual([]);
    expect(transformWarnings).toHaveLength(1);
    expect(transformWarnings[0].nodeId).toBe('tx');
    expect(transformWarnings[0].message).toContain('uppercase');
    expect(transformWarnings[0].message).toContain('passthrough');
    expect(result.valid).toBe(true);
  });

  it('emits a warning for non-string transform_type values', () => {
    const { nodes, edges } = buildFlow({ transform_type: 123 });
    const result = validateRule(nodes, edges);
    const transformErrors = result.errors.filter((e) => e.message.includes('Transform node'));
    const transformWarnings = result.warnings.filter((w) => w.message.includes('Transform node'));
    expect(transformErrors).toEqual([]);
    expect(transformWarnings).toHaveLength(1);
    expect(transformWarnings[0].nodeId).toBe('tx');
  });
});
