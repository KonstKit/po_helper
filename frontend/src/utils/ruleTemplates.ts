import { Node, Edge } from 'reactflow';

export interface RuleTemplate {
  id: string;
  name: string;
  description: string;
  category: 'basic' | 'advanced' | 'custom';
  nodes: Node[];
  edges: Edge[];
  tags: string[];
}

/**
 * Pre-built rule templates
 */
export const ruleTemplates: RuleTemplate[] = [
  {
    id: 'commit-to-subtask',
    name: 'Commit → Sub-task',
    description: 'Link commits to Jira sub-tasks by extracting keys from commit messages',
    category: 'basic',
    tags: ['git', 'jira', 'simple'],
    nodes: [
      {
        id: 'commit_1',
        type: 'commitSource',
        position: { x: 50, y: 100 },
        data: {
          label: 'Git Commit',
          filters: {
            branch: '',
            author: '',
            date_from: '',
            date_to: '',
          },
        },
      },
      {
        id: 'extractor_1',
        type: 'jiraKeyExtractor',
        position: { x: 300, y: 100 },
        data: {
          label: 'Extract Jira Keys',
          config: {
            search_in: ['message'],
            pattern: '\\b[A-Z][A-Z0-9_]+-[0-9]+\\b',
            case_sensitive: false,
            must_be_uppercase: true,
            extract_multiple: true,
          },
        },
      },
      {
        id: 'action_1',
        type: 'createLinkAction',
        position: { x: 550, y: 100 },
        data: {
          label: 'Create Link',
          config: {
            link_type: 'implements',
            bidirectional: false,
            reverse_link_type: '',
          },
        },
      },
    ],
    edges: [
      { id: 'e1-2', source: 'commit_1', target: 'extractor_1' },
      { id: 'e2-3', source: 'extractor_1', target: 'action_1' },
    ],
  },
  {
    id: 'bidirectional-story-link',
    name: 'Bidirectional Story Link',
    description: 'Create bidirectional links between commits and user stories',
    category: 'basic',
    tags: ['git', 'jira', 'bidirectional'],
    nodes: [
      {
        id: 'commit_1',
        type: 'commitSource',
        position: { x: 50, y: 100 },
        data: {
          label: 'Git Commit',
          filters: {
            branch: '',
            author: '',
            date_from: '',
            date_to: '',
          },
        },
      },
      {
        id: 'extractor_1',
        type: 'jiraKeyExtractor',
        position: { x: 300, y: 100 },
        data: {
          label: 'Extract Story Keys',
          config: {
            search_in: ['message', 'branch'],
            pattern: '\\b[A-Z][A-Z0-9_]+-[0-9]+\\b',
            case_sensitive: false,
            must_be_uppercase: true,
            extract_multiple: false,
          },
        },
      },
      {
        id: 'action_1',
        type: 'createLinkAction',
        position: { x: 550, y: 100 },
        data: {
          label: 'Create Bidirectional Link',
          config: {
            link_type: 'implements',
            bidirectional: true,
            reverse_link_type: 'implemented_by',
          },
        },
      },
    ],
    edges: [
      { id: 'e1-2', source: 'commit_1', target: 'extractor_1' },
      { id: 'e2-3', source: 'extractor_1', target: 'action_1' },
    ],
  },
  {
    id: 'confluence-to-jira',
    name: 'Confluence → Jira Stories',
    description: 'Link Confluence requirements pages to Jira user stories',
    category: 'basic',
    tags: ['confluence', 'jira', 'requirements'],
    nodes: [
      {
        id: 'confluence_1',
        type: 'confluenceSource',
        position: { x: 50, y: 100 },
        data: {
          label: 'Confluence Page',
          filters: {
            space: '',
            labels: ['requirements'],
          },
        },
      },
      {
        id: 'jira_1',
        type: 'jiraIssueSource',
        position: { x: 50, y: 250 },
        data: {
          label: 'Jira Stories',
          filters: {
            project: '',
            issue_type: ['Story'],
            status: [],
          },
        },
      },
      {
        id: 'action_1',
        type: 'createLinkAction',
        position: { x: 350, y: 175 },
        data: {
          label: 'Create Link',
          config: {
            link_type: 'relates_to',
            bidirectional: false,
            reverse_link_type: '',
          },
        },
      },
    ],
    edges: [
      { id: 'e1-3', source: 'confluence_1', target: 'action_1' },
      { id: 'e2-3', source: 'jira_1', target: 'action_1' },
    ],
  },
  {
    id: 'multi-source-advanced',
    name: 'Multi-source with Filtering',
    description: 'Advanced rule combining commits, Jira issues, and filtering by type',
    category: 'advanced',
    tags: ['git', 'jira', 'filter', 'complex'],
    nodes: [
      {
        id: 'commit_1',
        type: 'commitSource',
        position: { x: 50, y: 100 },
        data: {
          label: 'Recent Commits',
          filters: {
            branch: 'dev',
            author: '',
            date_from: '2025-01-01',
            date_to: '',
          },
        },
      },
      {
        id: 'extractor_1',
        type: 'jiraKeyExtractor',
        position: { x: 300, y: 100 },
        data: {
          label: 'Extract Keys',
          config: {
            search_in: ['message', 'branch'],
            pattern: '\\b[A-Z][A-Z0-9_]+-[0-9]+\\b',
            case_sensitive: false,
            must_be_uppercase: true,
            extract_multiple: true,
          },
        },
      },
      {
        id: 'jira_1',
        type: 'jiraIssueSource',
        position: { x: 550, y: 50 },
        data: {
          label: 'Sub-tasks Only',
          filters: {
            project: '',
            issue_type: ['Sub-task'],
            status: ['In Progress', 'In Review'],
          },
        },
      },
      {
        id: 'action_1',
        type: 'createLinkAction',
        position: { x: 800, y: 100 },
        data: {
          label: 'Link to Sub-task',
          config: {
            link_type: 'implements',
            bidirectional: true,
            reverse_link_type: 'implemented_by',
          },
        },
      },
    ],
    edges: [
      { id: 'e1-2', source: 'commit_1', target: 'extractor_1' },
      { id: 'e2-4', source: 'extractor_1', target: 'action_1' },
      { id: 'e3-4', source: 'jira_1', target: 'action_1' },
    ],
  },
];

/**
 * Get template by ID
 */
export function getTemplateById(id: string): RuleTemplate | undefined {
  return ruleTemplates.find((t) => t.id === id);
}

/**
 * Get templates by category
 */
export function getTemplatesByCategory(category: 'basic' | 'advanced' | 'custom'): RuleTemplate[] {
  return ruleTemplates.filter((t) => t.category === category);
}

/**
 * Get templates by tag
 */
export function getTemplatesByTag(tag: string): RuleTemplate[] {
  return ruleTemplates.filter((t) => t.tags.includes(tag));
}

/**
 * Apply template to canvas (returns nodes and edges with new IDs to avoid conflicts)
 */
export function applyTemplate(template: RuleTemplate): { nodes: Node[]; edges: Edge[] } {
  const timestamp = Date.now();
  const idMap = new Map<string, string>();

  // Create new nodes with unique IDs
  const nodes = template.nodes.map((node, index) => {
    const newId = `${node.type}_${timestamp}_${index}`;
    idMap.set(node.id, newId);
    return {
      ...node,
      id: newId,
      data: { ...node.data },
    };
  });

  // Create new edges with mapped IDs
  const edges = template.edges.map((edge, index) => ({
    ...edge,
    id: `e${timestamp}_${index}`,
    source: idMap.get(edge.source) || edge.source,
    target: idMap.get(edge.target) || edge.target,
  }));

  return { nodes, edges };
}
