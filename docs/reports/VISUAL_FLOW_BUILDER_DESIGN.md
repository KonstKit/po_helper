# Visual Flow Builder - Detailed Design

## Концепция

Drag-and-drop интерфейс для визуального создания правил трассируемости, вдохновлённый n8n/Node-RED/Apache NiFi.

---

## 1. UI Layout

```
┌─ Traceability Rule Builder ─────────────────────────────────────────────────┐
│                                                                               │
│  📁 File: [Commit → Sub-task Rule ▼] [Import JSON] [Export JSON] [Save]    │
│  ────────────────────────────────────────────────────────────────────────────│
│                                                                               │
│  ┌─ Toolbox ────────┐  ┌─ Canvas ──────────────────────────────────────┐   │
│  │                   │  │                                                 │   │
│  │ 📦 Sources        │  │   ┌─────────────┐                              │   │
│  │  • Commit         │  │   │   Commit    │                              │   │
│  │  • Jira Issue     │  │   │   Source    │                              │   │
│  │  • Confluence     │  │   └──────┬──────┘                              │   │
│  │  • Test Case      │  │          │ message, branch                     │   │
│  │  • Pull Request   │  │          ▼                                     │   │
│  │                   │  │   ┌─────────────┐      ┌──────────────┐       │   │
│  ├───────────────────┤  │   │  JIRA Key   │      │   Filter:    │       │   │
│  │ 🔍 Processors     │  │   │  Extractor  ├─────▶│  issue_type  │       │   │
│  │  • Regex Extract  │  │   └──────┬──────┘      │  = Sub-task  │       │   │
│  │  • JIRA Key       │  │          │ [WAB-123]   └──────┬───────┘       │   │
│  │  • Title Match    │  │          ▼                     │               │   │
│  │  • API Lookup     │  │   ┌─────────────┐             │               │   │
│  │  • Filter         │  │   │  Confidence │             ▼               │   │
│  │  • Transform      │  │   │  Calculator │      ┌─────────────┐        │   │
│  │                   │  │   └──────┬──────┘      │   Review    │        │   │
│  ├───────────────────┤  │          │ 90%         │   Queue     │        │   │
│  │ 🎯 Actions        │  │          ▼             │  (if <85%)  │        │   │
│  │  • Create Link    │  │   ┌─────────────┐     └─────────────┘        │   │
│  │  • Update Link    │  │   │  Create     │                             │   │
│  │  • Queue Review   │  │   │  Link       │                             │   │
│  │  • Send Alert     │  │   │  (impl...)  │                             │   │
│  │  • Log Event      │  │   └─────────────┘                             │   │
│  │                   │  │                                                 │   │
│  ├───────────────────┤  │   [Zoom: 100% ▼] [Fit to Screen] [Grid: On]   │   │
│  │ 🔗 Connectors     │  │                                                 │   │
│  │  • Forward        │  └─────────────────────────────────────────────────┘   │
│  │  • Bidirectional  │                                                        │
│  │  • Transitive     │  ┌─ Properties Panel ─────────────────────────────┐   │
│  │                   │  │ Selected: JIRA Key Extractor                    │   │
│  │ 💾 Templates      │  ├─────────────────────────────────────────────────┤   │
│  │  [+ Load]         │  │ Search in:                                      │   │
│  │  [💾 Save as]     │  │  ☑ Commit message                               │   │
│  │                   │  │  ☑ Branch name                                  │   │
│  └───────────────────┘  │  ☐ PR title                                     │   │
│                         │                                                  │   │
│                         │ Pattern: [WAB-\d+           ] [Test]            │   │
│                         │                                                  │   │
│                         │ Output:                                          │   │
│                         │  • Extracted keys: ${jira_keys}                 │   │
│                         │                                                  │   │
│                         │ [Apply Changes]                                  │   │
│                         └──────────────────────────────────────────────────┘   │
│                                                                               │
│  [Run Test] [Validate] [Clear Canvas] [Export JSON] [Save Rule]             │
└───────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Node Types (Building Blocks)

### 2.1 Source Nodes 📦

```typescript
interface SourceNode {
  type: 'source';
  subtype: 'commit' | 'jira_issue' | 'confluence_page' | 'test_case' | 'pull_request';
  config: {
    artifact_type: string;
    filters?: Record<string, any>;  // e.g., {"created_after": "2025-01-01"}
  };
  outputs: [{
    id: 'artifact',
    schema: ArtifactSchema  // Typed output for validation
  }];
}
```

**Visual:**
```
┌────────────────┐
│   📝 Commit    │
│    Source      │
├────────────────┤
│ Filters:       │
│ • branch: *    │
│ • author: all  │
└────────┬───────┘
         │ artifact
         ▼
```

### 2.2 Processor Nodes 🔍

#### JIRA Key Extractor
```typescript
interface JiraKeyExtractorNode {
  type: 'processor';
  subtype: 'jira_key_extractor';
  config: {
    search_in: ('message' | 'branch_name' | 'title' | 'body')[];
    pattern: string;  // regex
    case_sensitive: boolean;
    must_be_uppercase: boolean;
    extract_multiple: boolean;
  };
  inputs: [{
    id: 'artifact',
    accepts: ['Commit', 'PullRequest', 'ConfluencePage']
  }];
  outputs: [{
    id: 'jira_keys',
    type: 'string[]'
  }];
}
```

**Visual:**
```
┌────────────────┐
│  JIRA Key      │
│  Extractor     │
├────────────────┤
│ Pattern:       │
│ WAB-\d+        │
│ Search: msg ✓  │
└────────┬───────┘
         │ jira_keys
         ▼
```

#### Filter Node
```typescript
interface FilterNode {
  type: 'processor';
  subtype: 'filter';
  config: {
    conditions: Array<{
      field: string;          // e.g., "issue_type"
      operator: 'equals' | 'contains' | 'in' | 'regex';
      value: any;
    }>;
    mode: 'all' | 'any';      // AND / OR
  };
  inputs: [{ id: 'artifact' }];
  outputs: [
    { id: 'match', label: 'Match ✓' },
    { id: 'no_match', label: 'No Match ✗' }
  ];
}
```

**Visual:**
```
┌────────────────┐
│    Filter      │
├────────────────┤
│ issue_type     │
│ IN             │
│ [Sub-task,     │
│  Task, Bug]    │
└───┬────────┬───┘
    │ Match  │ No Match
    ▼        ▼
```

#### API Lookup Node
```typescript
interface ApiLookupNode {
  type: 'processor';
  subtype: 'api_lookup';
  config: {
    source: 'jira' | 'confluence' | 'gitlab';
    endpoint: string;           // e.g., "/issue/${jira_key}"
    id_field: string;           // Field from input to use as ID
    extract_path: string;       // JSON path to extract
    cache_ttl: number;          // Cache duration in seconds
  };
  inputs: [{ id: 'lookup_id' }];
  outputs: [
    { id: 'found', label: 'Found ✓' },
    { id: 'not_found', label: 'Not Found ✗' }
  ];
}
```

**Visual:**
```
┌────────────────┐
│  API Lookup    │
├────────────────┤
│ Source: Jira   │
│ Endpoint:      │
│ /issue/${key}  │
│ Extract:       │
│ $.fields.par.. │
└───┬────────┬───┘
    │ Found  │ Not Found
    ▼        ▼
```

#### Title Similarity Node
```typescript
interface TitleSimilarityNode {
  type: 'processor';
  subtype: 'title_similarity';
  config: {
    algorithm: 'levenshtein' | 'cosine' | 'jaccard';
    threshold: number;          // 0.0 - 1.0
    normalize: boolean;
    ignore_case: boolean;
  };
  inputs: [
    { id: 'source', label: 'Source Title' },
    { id: 'target', label: 'Target Title' }
  ];
  outputs: [
    { id: 'similarity_score', type: 'number' },
    { id: 'matches', label: 'Above Threshold' }
  ];
}
```

**Visual:**
```
┌────────────────┐
│    Title       │
│  Similarity    │
├────────────────┤
│ Algorithm:     │
│ Levenshtein    │
│ Threshold:     │
│ 0.75 ━━━━━░    │
└────────┬───────┘
         │ similarity
         ▼
```

#### Confidence Calculator Node
```typescript
interface ConfidenceCalculatorNode {
  type: 'processor';
  subtype: 'confidence_calculator';
  config: {
    base_confidence: number;
    factors: Array<{
      name: string;
      condition: string;        // JavaScript expression
      weight: number;           // +/- adjustment
    }>;
    min_confidence: number;
    max_confidence: number;
  };
  inputs: [{ id: 'context' }];
  outputs: [
    { id: 'confidence', type: 'number' },
    { id: 'tier', type: 'high' | 'medium' | 'low' }
  ];
}
```

**Visual:**
```
┌────────────────┐
│  Confidence    │
│  Calculator    │
├────────────────┤
│ Base: 90%      │
│ Factors:       │
│ • key_start +10│
│ • multi_key -5 │
└────────┬───────┘
         │ 95% (high)
         ▼
```

### 2.3 Action Nodes 🎯

#### Create Link Node
```typescript
interface CreateLinkNode {
  type: 'action';
  subtype: 'create_link';
  config: {
    link_type: string;
    bidirectional: boolean;
    reverse_link_type?: string;
    transitive: boolean;
    transitive_config?: {
      max_depth: number;
      strategies: string[];
    };
    conflict_resolution: 'keep_higher_priority' | 'keep_higher_confidence' | 'keep_both';
  };
  inputs: [
    { id: 'source_artifact' },
    { id: 'target_artifact' },
    { id: 'confidence', optional: true }
  ];
  outputs: [
    { id: 'created', label: 'Created ✓' },
    { id: 'skipped', label: 'Skipped (conflict)' }
  ];
}
```

**Visual:**
```
┌────────────────┐
│  Create Link   │
├────────────────┤
│ Type:          │
│ implements     │
│ ↔ Bidirect. ✓  │
│ Reverse:       │
│ implemented_by │
└───┬────────┬───┘
    │ Created│ Skipped
    ▼        ▼
```

#### Review Queue Node
```typescript
interface ReviewQueueNode {
  type: 'action';
  subtype: 'review_queue';
  config: {
    assign_to: 'auto' | 'user_id' | 'role';
    priority_formula: string;  // JavaScript expression
    context_fields: string[];  // What to show in review UI
  };
  inputs: [
    { id: 'link' },
    { id: 'confidence' }
  ];
  outputs: [{ id: 'queued' }];
}
```

**Visual:**
```
┌────────────────┐
│  Review Queue  │
├────────────────┤
│ Assign: Auto   │
│ Priority:      │
│ 100-confidence │
└────────┬───────┘
         │ queued
         ▼
```

### 2.4 Decision Nodes 🔀

#### If/Else Node
```typescript
interface DecisionNode {
  type: 'decision';
  subtype: 'if_else';
  config: {
    condition: string;  // JavaScript expression: ${confidence} >= 85
  };
  inputs: [{ id: 'input' }];
  outputs: [
    { id: 'true', label: 'True ✓' },
    { id: 'false', label: 'False ✗' }
  ];
}
```

**Visual:**
```
    ┌────────────────┐
    │   If/Else      │
    ├────────────────┤
    │ ${confidence}  │
    │     >= 85?     │
    └───┬────────┬───┘
        │ Yes    │ No
        ▼        ▼
```

#### Switch Node
```typescript
interface SwitchNode {
  type: 'decision';
  subtype: 'switch';
  config: {
    expression: string;
    cases: Array<{
      value: any;
      label: string;
    }>;
  };
  inputs: [{ id: 'input' }];
  outputs: [
    ...cases.map(c => ({ id: c.value, label: c.label })),
    { id: 'default', label: 'Default' }
  ];
}
```

**Visual:**
```
    ┌────────────────┐
    │    Switch      │
    ├────────────────┤
    │ ${tier}        │
    └───┬─────┬──┬───┘
        │ High│Med│Low
        ▼     ▼  ▼
```

---

## 3. Canvas Interactions

### 3.1 Node Operations

**Add Node:**
```typescript
// Drag from toolbox to canvas
onDrop(event: DragEvent) {
  const nodeType = event.dataTransfer.getData('nodeType');
  const position = { x: event.clientX, y: event.clientY };

  const newNode = createNode(nodeType, position);
  addNodeToCanvas(newNode);
}
```

**Connect Nodes:**
```typescript
// Click output port → drag → click input port
onConnectionStart(sourceNode: Node, outputPort: Port) {
  startConnection(sourceNode, outputPort);
}

onConnectionEnd(targetNode: Node, inputPort: Port) {
  const edge = createEdge(
    currentConnection.source,
    currentConnection.outputPort,
    targetNode,
    inputPort
  );

  // Validate connection type compatibility
  if (isValidConnection(edge)) {
    addEdgeToCanvas(edge);
  } else {
    showError('Incompatible types: cannot connect ${source.type} to ${target.type}');
  }
}
```

**Configure Node:**
```typescript
onClick(node: Node) {
  selectNode(node);
  showPropertiesPanel(node);
}

onDoubleClick(node: Node) {
  openNodeEditor(node);  // Full-screen modal with advanced settings
}
```

### 3.2 Canvas Controls

**Zoom & Pan:**
- Mouse wheel: zoom in/out
- Middle mouse drag: pan
- Pinch gesture: zoom (touch)
- Fit to screen button
- Zoom to selection

**Grid & Snapping:**
- Toggle grid on/off
- Snap to grid (10px increments)
- Smart guides when aligning nodes

**Multi-select:**
- Click-drag rectangle selection
- Ctrl+Click to add to selection
- Delete key to remove selected

---

## 4. JSON Import/Export Schema

### 4.1 Export Format

```json
{
  "version": "2.0",
  "metadata": {
    "name": "Commit → Sub-task Rule",
    "description": "Links commits to Jira sub-tasks via issue keys",
    "author": "user@example.com",
    "created_at": "2025-10-05T10:30:00Z",
    "tags": ["jira", "git", "wabank"]
  },
  "nodes": [
    {
      "id": "node_1",
      "type": "source",
      "subtype": "commit",
      "position": { "x": 100, "y": 100 },
      "config": {
        "artifact_type": "Commit",
        "filters": {}
      }
    },
    {
      "id": "node_2",
      "type": "processor",
      "subtype": "jira_key_extractor",
      "position": { "x": 300, "y": 100 },
      "config": {
        "search_in": ["message", "branch_name"],
        "pattern": "\\b[A-Z][A-Z0-9_]+-[0-9]+\\b",
        "case_sensitive": false,
        "must_be_uppercase": true,
        "extract_multiple": false
      }
    },
    {
      "id": "node_3",
      "type": "processor",
      "subtype": "api_lookup",
      "position": { "x": 500, "y": 100 },
      "config": {
        "source": "jira",
        "endpoint": "/issue/${jira_key}",
        "id_field": "jira_keys[0]",
        "extract_path": "$",
        "cache_ttl": 300
      }
    },
    {
      "id": "node_4",
      "type": "processor",
      "subtype": "filter",
      "position": { "x": 700, "y": 100 },
      "config": {
        "conditions": [
          {
            "field": "fields.issuetype.name",
            "operator": "in",
            "value": ["Sub-task", "Task", "Bug"]
          }
        ],
        "mode": "all"
      }
    },
    {
      "id": "node_5",
      "type": "processor",
      "subtype": "confidence_calculator",
      "position": { "x": 700, "y": 250 },
      "config": {
        "base_confidence": 90,
        "factors": [
          {
            "name": "key_at_start",
            "condition": "${commit.message}.trimStart().startsWith(${jira_key})",
            "weight": 10
          },
          {
            "name": "multiple_keys",
            "condition": "${jira_keys}.length > 1",
            "weight": -5
          }
        ],
        "min_confidence": 0,
        "max_confidence": 100
      }
    },
    {
      "id": "node_6",
      "type": "decision",
      "subtype": "if_else",
      "position": { "x": 900, "y": 250 },
      "config": {
        "condition": "${confidence} >= 85"
      }
    },
    {
      "id": "node_7",
      "type": "action",
      "subtype": "create_link",
      "position": { "x": 1100, "y": 200 },
      "config": {
        "link_type": "implements",
        "bidirectional": true,
        "reverse_link_type": "implemented_by",
        "transitive": false,
        "conflict_resolution": "keep_higher_confidence"
      }
    },
    {
      "id": "node_8",
      "type": "action",
      "subtype": "review_queue",
      "position": { "x": 1100, "y": 350 },
      "config": {
        "assign_to": "auto",
        "priority_formula": "100 - ${confidence}",
        "context_fields": ["commit.message", "jira_issue.summary", "confidence"]
      }
    }
  ],
  "edges": [
    {
      "id": "edge_1",
      "source": "node_1",
      "source_port": "artifact",
      "target": "node_2",
      "target_port": "artifact"
    },
    {
      "id": "edge_2",
      "source": "node_2",
      "source_port": "jira_keys",
      "target": "node_3",
      "target_port": "lookup_id"
    },
    {
      "id": "edge_3",
      "source": "node_3",
      "source_port": "found",
      "target": "node_4",
      "target_port": "artifact"
    },
    {
      "id": "edge_4",
      "source": "node_4",
      "source_port": "match",
      "target": "node_5",
      "target_port": "context"
    },
    {
      "id": "edge_5",
      "source": "node_5",
      "source_port": "confidence",
      "target": "node_6",
      "target_port": "input"
    },
    {
      "id": "edge_6",
      "source": "node_6",
      "source_port": "true",
      "target": "node_7",
      "target_port": "source_artifact"
    },
    {
      "id": "edge_7",
      "source": "node_6",
      "source_port": "false",
      "target": "node_8",
      "target_port": "link"
    }
  ],
  "variables": {
    "project_key_pattern": "WAB",
    "min_auto_approve_confidence": 85
  }
}
```

### 4.2 Import Validation

```typescript
interface ImportValidator {
  validateSchema(json: any): ValidationResult;
  checkNodeTypes(nodes: Node[]): ValidationResult;
  checkConnections(edges: Edge[]): ValidationResult;
  migrateVersion(json: any, targetVersion: string): any;
}

// Example validation
const validator = new ImportValidator();

const result = validator.validateSchema(importedJSON);
if (!result.valid) {
  showErrors(result.errors);
  return;
}

// Auto-migrate from v1.0 to v2.0
if (importedJSON.version === '1.0') {
  importedJSON = validator.migrateVersion(importedJSON, '2.0');
}

// Load to canvas
loadFlowToCanvas(importedJSON);
```

---

## 5. React Component Structure

### 5.1 Main Components

```typescript
// FlowBuilder.tsx
const FlowBuilder: React.FC = () => {
  const [nodes, setNodes] = useState<Node[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [selectedNode, setSelectedNode] = useState<Node | null>(null);

  return (
    <Box sx={{ height: '100vh', display: 'flex' }}>
      {/* Toolbox */}
      <Toolbox onDragStart={handleDragStart} />

      {/* Canvas */}
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={(e, node) => setSelectedNode(node)}
        fitView
      >
        <Background />
        <Controls />
        <MiniMap />
      </ReactFlow>

      {/* Properties Panel */}
      <PropertiesPanel
        node={selectedNode}
        onChange={handleNodeUpdate}
      />
    </Box>
  );
};
```

### 5.2 Custom Node Component

```typescript
// CustomNode.tsx
const CustomNode: React.FC<NodeProps> = ({ data, selected }) => {
  return (
    <Paper
      elevation={selected ? 8 : 2}
      sx={{
        minWidth: 200,
        border: selected ? '2px solid #1976d2' : 'none',
      }}
    >
      {/* Header */}
      <Box sx={{ bgcolor: getNodeColor(data.type), p: 1 }}>
        <Stack direction="row" spacing={1} alignItems="center">
          <NodeIcon type={data.subtype} />
          <Typography variant="subtitle2" color="white">
            {data.label || data.subtype}
          </Typography>
        </Stack>
      </Box>

      {/* Input Ports */}
      {data.inputs?.map((input, idx) => (
        <Handle
          key={input.id}
          type="target"
          position={Position.Left}
          id={input.id}
          style={{ top: `${(idx + 1) * 30}px` }}
        />
      ))}

      {/* Body */}
      <Box sx={{ p: 1.5 }}>
        <NodeSummary config={data.config} />
      </Box>

      {/* Output Ports */}
      {data.outputs?.map((output, idx) => (
        <Handle
          key={output.id}
          type="source"
          position={Position.Right}
          id={output.id}
          style={{ top: `${(idx + 1) * 30}px` }}
        />
      ))}
    </Paper>
  );
};
```

### 5.3 Import/Export Components

```typescript
// ImportExportDialog.tsx
const ImportExportDialog: React.FC = () => {
  const [mode, setMode] = useState<'import' | 'export'>('export');
  const [json, setJson] = useState<string>('');

  const handleExport = () => {
    const flowJSON = exportFlowToJSON(nodes, edges, metadata);
    setJson(JSON.stringify(flowJSON, null, 2));
  };

  const handleImport = () => {
    try {
      const flowData = JSON.parse(json);
      const validation = validateImport(flowData);

      if (!validation.valid) {
        showErrors(validation.errors);
        return;
      }

      importFlowFromJSON(flowData);
      onClose();
    } catch (error) {
      showError('Invalid JSON: ' + error.message);
    }
  };

  const handleFileImport = (file: File) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      setJson(e.target.result as string);
    };
    reader.readAsText(file);
  };

  return (
    <Dialog open={open} maxWidth="md" fullWidth>
      <DialogTitle>
        <Tabs value={mode} onChange={(e, v) => setMode(v)}>
          <Tab label="Export" value="export" />
          <Tab label="Import" value="import" />
        </Tabs>
      </DialogTitle>

      <DialogContent>
        {mode === 'export' ? (
          <Box>
            <Button onClick={handleExport} variant="contained" sx={{ mb: 2 }}>
              Generate JSON
            </Button>
            <TextField
              multiline
              rows={20}
              value={json}
              fullWidth
              InputProps={{
                readOnly: true,
                sx: { fontFamily: 'monospace', fontSize: 12 }
              }}
            />
            <Stack direction="row" spacing={2} sx={{ mt: 2 }}>
              <Button
                startIcon={<ContentCopyIcon />}
                onClick={() => navigator.clipboard.writeText(json)}
              >
                Copy to Clipboard
              </Button>
              <Button
                startIcon={<DownloadIcon />}
                onClick={() => downloadJSON(json, `rule_${Date.now()}.json`)}
              >
                Download File
              </Button>
            </Stack>
          </Box>
        ) : (
          <Box>
            <Stack direction="row" spacing={2} sx={{ mb: 2 }}>
              <Button
                variant="contained"
                component="label"
              >
                Upload File
                <input
                  type="file"
                  accept=".json"
                  hidden
                  onChange={(e) => handleFileImport(e.target.files[0])}
                />
              </Button>
              <Typography variant="caption">
                or paste JSON below
              </Typography>
            </Stack>

            <TextField
              multiline
              rows={20}
              value={json}
              onChange={(e) => setJson(e.target.value)}
              fullWidth
              placeholder="Paste JSON here..."
              InputProps={{
                sx: { fontFamily: 'monospace', fontSize: 12 }
              }}
            />

            <Button
              variant="contained"
              onClick={handleImport}
              sx={{ mt: 2 }}
              fullWidth
            >
              Import Flow
            </Button>
          </Box>
        )}
      </DialogContent>
    </Dialog>
  );
};
```

---

## 6. Library: React Flow

**Recommendation:** Use **[React Flow](https://reactflow.dev/)** (formerly react-flow-renderer)

### Why React Flow?

✅ **Production-ready** (used by Stripe, Typeform, etc.)
✅ **Rich features** (zoom, pan, minimap, controls)
✅ **Custom nodes** support
✅ **TypeScript** first-class support
✅ **Performance** optimized for 1000+ nodes
✅ **Plugin system** (minimap, controls, background)
✅ **Open source** MIT license

### Installation

```bash
cd frontend
npm install reactflow
```

### Basic Setup

```typescript
// pages/TraceabilityFlowBuilder.tsx
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  addEdge,
  Connection,
  Edge,
  Node,
} from 'reactflow';
import 'reactflow/dist/style.css';

const initialNodes: Node[] = [];
const initialEdges: Edge[] = [];

export default function TraceabilityFlowBuilder() {
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  const onConnect = useCallback(
    (params: Connection) => setEdges((eds) => addEdge(params, eds)),
    [setEdges]
  );

  return (
    <Box sx={{ width: '100vw', height: '100vh' }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        fitView
      >
        <Background />
        <Controls />
        <MiniMap />
      </ReactFlow>
    </Box>
  );
}
```

---

## 7. Implementation Phases

### Phase 1: Foundation (Week 1-2)
- [ ] Setup React Flow
- [ ] Create basic node types (Source, Processor, Action)
- [ ] Implement drag-and-drop from toolbox
- [ ] Basic node connections
- [ ] Properties panel (read-only)

### Phase 2: Node Library (Week 3-4)
- [ ] Implement all processor nodes:
  - JIRA Key Extractor
  - Filter
  - API Lookup
  - Title Similarity
  - Confidence Calculator
- [ ] Implement action nodes:
  - Create Link
  - Review Queue
- [ ] Decision nodes (If/Else, Switch)

### Phase 3: Configuration (Week 5)
- [ ] Editable properties panel
- [ ] Form validation
- [ ] Real-time preview for regex/patterns
- [ ] Node-specific editors

### Phase 4: Import/Export (Week 6)
- [ ] JSON export with metadata
- [ ] JSON import with validation
- [ ] Version migration (v1 → v2)
- [ ] File upload/download
- [ ] Template library

### Phase 5: Execution Engine (Week 7-8)
- [ ] Convert flow to executable pipeline
- [ ] Test mode (dry-run)
- [ ] Error handling and logging
- [ ] Performance optimization

### Phase 6: Polish (Week 9-10)
- [ ] Keyboard shortcuts
- [ ] Undo/redo
- [ ] Auto-save
- [ ] Collaborative editing (future)
- [ ] Templates gallery

---

## 8. Example Templates

### Template 1: Simple (Commit → Task)

```json
{
  "name": "Simple: Commit → Task",
  "nodes": [
    {"type": "source", "subtype": "commit"},
    {"type": "processor", "subtype": "jira_key_extractor"},
    {"type": "processor", "subtype": "api_lookup"},
    {"type": "action", "subtype": "create_link"}
  ]
}
```

### Template 2: Advanced (Confidence-based Review)

```json
{
  "name": "Advanced: Commit → Task with Review",
  "nodes": [
    {"type": "source", "subtype": "commit"},
    {"type": "processor", "subtype": "jira_key_extractor"},
    {"type": "processor", "subtype": "api_lookup"},
    {"type": "processor", "subtype": "filter"},
    {"type": "processor", "subtype": "confidence_calculator"},
    {"type": "decision", "subtype": "if_else"},
    {"type": "action", "subtype": "create_link"},
    {"type": "action", "subtype": "review_queue"}
  ]
}
```

### Template 3: Multi-source (Confluence + Jira)

```json
{
  "name": "Multi-source: Confluence → User Story → Sub-task",
  "nodes": [
    {"type": "source", "subtype": "confluence_page"},
    {"type": "processor", "subtype": "jira_key_extractor"},
    {"type": "processor", "subtype": "api_lookup"},
    {"type": "processor", "subtype": "filter", "config": {"issue_type": "User Story"}},
    {"type": "action", "subtype": "create_link"},
    // Second branch
    {"type": "source", "subtype": "commit"},
    {"type": "processor", "subtype": "jira_key_extractor"},
    {"type": "processor", "subtype": "api_lookup"},
    {"type": "processor", "subtype": "filter", "config": {"issue_type": "Sub-task"}},
    {"type": "action", "subtype": "create_link"}
  ]
}
```

---

## 9. Next Steps

1. **Approve design?** Any changes needed?
2. **Start Phase 1?** Setup React Flow + basic nodes
3. **Define node schemas?** Detailed TypeScript interfaces
4. **Create mockups?** Figma/screenshots of actual UI

Готовы начать реализацию Visual Flow Builder?
