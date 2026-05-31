import React from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  FormControl,
  Grid,
  InputLabel,
  LinearProgress,
  MenuItem,
  Paper,
  Select,
  Skeleton,
  Tab,
  Tabs,
  TextField,
  Typography,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
} from "@mui/material";
import type { SelectChangeEvent } from "@mui/material/Select";
import { DataGrid, GridColDef, GridPaginationModel } from "@mui/x-data-grid";
import { Line } from "react-chartjs-2";

import CircularProgressWithLabel from "../../components/CircularProgressWithLabel";
import { getCanonicalSprintId, getSprintStateLabel } from "../../utils/sprintNormalization";
import type {
  Board,
  BurndownPoint,
  BurndownResponse,
  ProjectRepositoryLink,
  QualityHistoryItem,
  RisksResponse,
  RiskItem,
  Sprint,
  SprintCapacity,
  SprintQuality,
  TaskItem,
  TeamMemberActivity,
} from "../../services/api";

type ThresholdsState = {
  min_line?: number | "";
  min_branch?: number | "";
};

type BulkProgressState = {
  active: boolean;
  percent: number;
  step: string;
};

type RepoActionState = { type: "primary" | "remove"; id: number } | null;

// Per-section loading flags driven by ProjectDetail's independent data loads.
// Each section renders its own in-place skeleton while its flag is true.
type SectionLoadingState = {
  metrics: boolean;
  tasks: boolean;
  burndown: boolean;
  team: boolean;
  risks: boolean;
  sprints: boolean;
  sprintInsights: boolean;
};

type ProjectDetailTabsProps = {
  value: number;
  onChange: (event: React.SyntheticEvent, newValue: number) => void;
  sectionLoading: SectionLoadingState;
  rows: TaskItem[];
  taskColumns: GridColDef[];
  taskPaginationModel: GridPaginationModel;
  onTaskPaginationModelChange: (model: GridPaginationModel) => void;
  taskRowCount: number;
  burndown: BurndownResponse | null;
  teamMembers: TeamMemberActivity[];
  risks: RisksResponse | null;
  boards: Board[];
  boardId: number | "";
  sprints: Sprint[];
  selectedSprint: number | "";
  sprintBurndown: BurndownResponse | null;
  sprintQuality: SprintQuality | null;
  sprintCapacity: SprintCapacity | null;
  onBoardChange: (boardId: number) => Promise<void>;
  onSprintChange: (sprintId: number) => Promise<void>;
  thresholds: ThresholdsState;
  setThresholds: React.Dispatch<React.SetStateAction<ThresholdsState>>;
  qualityLoading: boolean;
  hist: QualityHistoryItem[];
  bulkProgress: BulkProgressState;
  onSaveThresholds: () => Promise<void>;
  onBulkCheck: () => Promise<void>;
  repoProviders: { github: boolean; gitlab: boolean };
  repoLoading: boolean;
  repoBindings: ProjectRepositoryLink[];
  repoAction: RepoActionState;
  onOpenRepoDialog: () => void;
  onSetPrimaryRepository: (binding: ProjectRepositoryLink) => Promise<void>;
  onRemoveRepository: (binding: ProjectRepositoryLink) => Promise<void>;
};

interface TeamMemberDisplay {
  name: string;
  email?: string;
  active_tasks: number;
  last_activity: string | null;
  days_since_activity: number | null;
}

interface TabPanelProps {
  children?: React.ReactNode;
  index: number;
  value: number;
}

function TabPanel(props: TabPanelProps) {
  const { children, value, index, ...other } = props;

  return (
    <div
      role="tabpanel"
      hidden={value !== index}
      id={`project-tabpanel-${index}`}
      aria-labelledby={`project-tab-${index}`}
      {...other}
    >
      {value === index && <Box sx={{ p: 3 }}>{children}</Box>}
    </div>
  );
}

const ProjectDetailTabs = ({
  value,
  onChange,
  sectionLoading,
  rows,
  taskColumns,
  taskPaginationModel,
  onTaskPaginationModelChange,
  taskRowCount,
  burndown,
  teamMembers,
  risks,
  boards,
  boardId,
  sprints,
  selectedSprint,
  sprintBurndown,
  sprintQuality,
  sprintCapacity,
  onBoardChange,
  onSprintChange,
  thresholds,
  setThresholds,
  qualityLoading,
  hist,
  bulkProgress,
  onSaveThresholds,
  onBulkCheck,
  repoProviders,
  repoLoading,
  repoBindings,
  repoAction,
  onOpenRepoDialog,
  onSetPrimaryRepository,
  onRemoveRepository,
}: ProjectDetailTabsProps) => (
  <Paper>
    <Tabs value={value} onChange={onChange}>
      <Tab label="Tasks" />
      <Tab label="Progress" />
      <Tab label="Team" />
      <Tab label="Risks" />
      <Tab label="Sprints" />
      <Tab label="Quality" />
      <Tab label="Repositories" />
    </Tabs>

    <TabPanel value={value} index={0}>
      <Box height={500}>
        {sectionLoading.tasks && rows.length === 0 ? (
          <Box>
            <Skeleton variant="rectangular" width="100%" height={56} sx={{ mb: 1, borderRadius: 1 }} />
            {Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} variant="rectangular" width="100%" height={40} sx={{ mb: 0.5, borderRadius: 1 }} />
            ))}
          </Box>
        ) : (
          <DataGrid
            rows={rows}
            columns={taskColumns}
            loading={sectionLoading.tasks}
            checkboxSelection
            disableRowSelectionOnClick
            paginationMode="server"
            rowCount={taskRowCount}
            paginationModel={taskPaginationModel}
            onPaginationModelChange={onTaskPaginationModelChange}
            pageSizeOptions={[25, 50, 100]}
          />
        )}
      </Box>
    </TabPanel>

    <TabPanel value={value} index={1}>
      <Box height={400}>
        <Typography variant="h6" gutterBottom>
          Project Burndown
        </Typography>
        {sectionLoading.burndown && !burndown ? (
          <Skeleton variant="rectangular" width="100%" height={340} sx={{ borderRadius: 1 }} />
        ) : (
        <Line
          data={{
            labels: (burndown?.ideal_burndown || []).map(
              (p: BurndownPoint) => `Day ${p.day}`,
            ),
            datasets: [
              {
                label: "Ideal",
                data: (burndown?.ideal_burndown || []).map(
                  (p: BurndownPoint) => p.ideal_remaining,
                ),
                borderColor: "rgba(255,99,132,0.8)",
                backgroundColor: "rgba(255,99,132,0.1)",
                borderDash: [5, 5],
              },
              {
                label: "Actual",
                data: (
                  burndown?.actual_burndown ||
                  burndown?.ideal_burndown ||
                  []
                ).map((p: BurndownPoint) => p.remaining || p.ideal_remaining),
                borderColor: "rgba(54,162,235,0.8)",
                backgroundColor: "rgba(54,162,235,0.1)",
              },
            ],
          }}
          options={{
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { position: "top" } },
          }}
        />
        )}
      </Box>
    </TabPanel>

    <TabPanel value={value} index={2}>
      <Typography variant="h6" gutterBottom>
        Team Members
      </Typography>
      {sectionLoading.team && teamMembers.length === 0 && rows.length === 0 ? (
        <Grid container spacing={2}>
          {Array.from({ length: 4 }).map((_, i) => (
            <Grid item xs={12} sm={6} md={3} key={i}>
              <Card>
                <CardContent>
                  <Skeleton variant="text" width="70%" height={28} />
                  <Skeleton variant="text" width="50%" height={20} />
                  <Skeleton variant="text" width="60%" height={16} />
                </CardContent>
              </Card>
            </Grid>
          ))}
        </Grid>
      ) : (
      <Grid container spacing={2}>
        {(teamMembers.length > 0
          ? teamMembers.map((m): TeamMemberDisplay => ({
              name: m.assignee || m.name || m.email || "unassigned",
              email: m.email ?? undefined,
              active_tasks: m.active_tasks ?? m.count ?? 0,
              last_activity: m.last_activity ?? null,
              days_since_activity: m.days_since_activity ?? null,
            }))
          : Array.from(
              new Map(
                rows
                  .filter((r) => r.assignee_name)
                  .map((r) => [r.assignee_name, r] as const),
              ).values(),
            ).map((r): TeamMemberDisplay => ({
              name: r.assignee_name || "",
              active_tasks: rows.filter((x) => x.assignee_name === r.assignee_name)
                .length,
              last_activity: null,
              days_since_activity: null,
            }))
        ).map((member) => (
          <Grid item xs={12} sm={6} md={3} key={member.name}>
            <Card>
              <CardContent>
                <Typography variant="h6">{member.name}</Typography>
                <Typography variant="body2" color="text.secondary">
                  {member.active_tasks} active tasks
                </Typography>
                {member.last_activity && (
                  <Typography
                    variant="caption"
                    color={
                      member.days_since_activity === null
                        ? "text.disabled"
                        : member.days_since_activity === 0
                          ? "success.main"
                          : member.days_since_activity <= 3
                            ? "info.main"
                            : member.days_since_activity <= 7
                              ? "warning.main"
                              : "error.main"
                    }
                  >
                    Last activity:{" "}
                    {member.days_since_activity === 0
                      ? "today"
                      : member.days_since_activity === 1
                        ? "yesterday"
                        : `${member.days_since_activity} days ago`}
                  </Typography>
                )}
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>
      )}
    </TabPanel>

    <TabPanel value={value} index={3}>
      <Typography variant="h6" gutterBottom>
        Risk Assessment
      </Typography>
      {sectionLoading.risks && !risks ? (
        <Box>
          {Array.from({ length: 3 }).map((_, i) => (
            <Card key={i} sx={{ mb: 2 }}>
              <CardContent>
                <Box display="flex" alignItems="center" gap={2}>
                  <Skeleton variant="rounded" width={80} height={32} />
                  <Skeleton variant="text" width="60%" height={24} />
                </Box>
              </CardContent>
            </Card>
          ))}
        </Box>
      ) : (
      <Box>
        {(risks?.risks || []).map((risk: RiskItem, index: number) => (
          <Card key={index} sx={{ mb: 2 }}>
            <CardContent>
              <Box display="flex" alignItems="center" gap={2}>
                <Chip
                  label={risk.type || risk.task_key || "Risk"}
                  color={
                    risk.severity === "high"
                      ? "error"
                      : risk.severity === "medium"
                        ? "warning"
                        : "success"
                  }
                />
                <Typography>{risk.message || risk.description || "—"}</Typography>
              </Box>
            </CardContent>
          </Card>
        ))}
      </Box>
      )}
    </TabPanel>

    <TabPanel value={value} index={4}>
      <Box mb={2} display="flex" alignItems="center" gap={2}>
        <FormControl size="small" sx={{ minWidth: 220 }}>
          <InputLabel>Board</InputLabel>
          <Select<string>
            label="Board"
            value={boardId === "" ? "" : String(boardId)}
            onChange={(event: SelectChangeEvent<string>) => {
              const next = Number(event.target.value);
              if (Number.isFinite(next)) {
                void onBoardChange(next);
              }
            }}
          >
            {boards.map((b) => (
              <MenuItem key={b.id} value={String(b.id)}>
                {b.name}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        <FormControl size="small" sx={{ minWidth: 220 }}>
          <InputLabel>Sprint</InputLabel>
          <Select<string>
            label="Sprint"
            value={selectedSprint === "" ? "" : String(selectedSprint)}
            onChange={(event: SelectChangeEvent<string>) => {
              const next = Number(event.target.value);
              if (Number.isFinite(next)) {
                void onSprintChange(next);
              }
            }}
          >
            {sprints.length === 0 && (
              <MenuItem disabled value="">
                No sprints found for selected board
              </MenuItem>
            )}
            {sprints.map((s) => {
              const sprintId = getCanonicalSprintId(s);
              if (typeof sprintId !== "number") return null;
              return (
                <MenuItem key={sprintId} value={String(sprintId)}>
                  {s.name} ({getSprintStateLabel(s)})
                </MenuItem>
              );
            })}
          </Select>
        </FormControl>
      </Box>

      {/* Sprint analytics: skeleton while its (slowest) data loads. The board /
          sprint selectors above stay interactive throughout. */}
      {(sectionLoading.sprints || sectionLoading.sprintInsights) &&
      !sprintBurndown &&
      !sprintQuality &&
      !sprintCapacity ? (
        <>
          <Grid container spacing={2} mb={2}>
            {Array.from({ length: 6 }).map((_, i) => (
              <Grid item xs={12} sm={6} md={2} key={i}>
                <Card>
                  <CardContent>
                    <Skeleton variant="text" width="70%" height={20} />
                    <Skeleton variant="text" width="50%" height={32} />
                  </CardContent>
                </Card>
              </Grid>
            ))}
          </Grid>
          <Paper sx={{ p: 2, mb: 2 }}>
            <Skeleton variant="text" width={120} height={28} sx={{ mb: 1 }} />
            <Skeleton variant="rectangular" width="100%" height={300} sx={{ borderRadius: 1 }} />
          </Paper>
          <Paper sx={{ p: 2 }}>
            <Skeleton variant="text" width={120} height={28} sx={{ mb: 1 }} />
            <Grid container spacing={2}>
              {Array.from({ length: 3 }).map((_, i) => (
                <Grid item xs={12} sm={4} key={i}>
                  <Card>
                    <CardContent>
                      <Skeleton variant="text" width="60%" height={20} />
                      <Skeleton variant="text" width="40%" height={32} />
                    </CardContent>
                  </Card>
                </Grid>
              ))}
            </Grid>
          </Paper>
        </>
      ) : (
      <>
      <Grid container spacing={2} mb={2}>
        {(() => {
          const current = sprints.find(
            (s) => getCanonicalSprintId(s) === selectedSprint,
          );
          if (!current) return null;

          const commitmentHours = current.commitment_hours ?? current.commitment ?? 0;
          const completedHours = current.completed_hours ?? current.completed ?? 0;
          const scopeAddedHours = current.scope_added_hours ?? 0;
          const predictabilityPct =
            current.predictability_pct ??
            (commitmentHours > 0
              ? (completedHours / commitmentHours) * 100
              : 0);
          const carryoverHours = current.carryover_hours ?? 0;

          let forecastLabel = "N/A";
          try {
            const startDate = current.start_date;
            const endDate = current.end_date;
            if (startDate && endDate) {
              const sd = new Date(startDate).getTime();
              const ed = new Date(endDate).getTime();
              const now = Date.now();
              const totalDays = Math.max(1, (ed - sd) / (1000 * 3600 * 24));
              const elapsedDays = Math.max(
                0,
                Math.min(totalDays, (now - sd) / (1000 * 3600 * 24)),
              );
              const commit = Number(commitmentHours);
              const completed = Number(completedHours);
              const remaining = Math.max(commit - completed, 0);
              const daysLeft = Math.max(0.1, totalDays - elapsedDays);
              const paceNeeded = remaining / daysLeft;
              const paceCurrent = elapsedDays > 0 ? completed / elapsedDays : 0;
              const onTrack =
                paceCurrent + 0.01 >=
                (commit / totalDays) * (elapsedDays / totalDays)
                  ? completed / commit >= elapsedDays / totalDays - 0.05
                  : completed / commit >= elapsedDays / totalDays - 0.05;
              forecastLabel = `${onTrack ? "On track" : "At risk"} — need ${Math.round(paceNeeded * 10) / 10}h/day`;
            }
          } catch (err) {
            void err;
          }
          const cards = [
            {
              title: "Commitment",
              value: `${typeof commitmentHours === "number" ? commitmentHours.toFixed(1) : commitmentHours}h`,
            },
            {
              title: "Completed",
              value: `${typeof completedHours === "number" ? completedHours.toFixed(1) : completedHours}h`,
            },
            {
              title: "Scope Change",
              value: `${typeof scopeAddedHours === "number" ? scopeAddedHours.toFixed(1) : scopeAddedHours}h`,
            },
            {
              title: "Predictability",
              value: `${typeof predictabilityPct === "number" ? predictabilityPct.toFixed(1) : predictabilityPct}%`,
            },
            {
              title: "Carryover",
              value: `${typeof carryoverHours === "number" ? carryoverHours.toFixed(1) : carryoverHours}h`,
            },
            { title: "Forecast", value: forecastLabel },
          ];
          return cards.map((c, idx) => (
            <Grid item xs={12} sm={6} md={2} key={idx}>
              <Card>
                <CardContent>
                  <Typography color="textSecondary" gutterBottom>
                    {c.title}
                  </Typography>
                  <Typography variant="h5">{c.value}</Typography>
                </CardContent>
              </Card>
            </Grid>
          ));
        })()}
      </Grid>

      <Paper sx={{ p: 2, mb: 2 }}>
        <Typography variant="h6" gutterBottom>
          Burndown
        </Typography>
        <Box height={300}>
          <Line
            data={{
              labels: (sprintBurndown?.ideal_burndown || []).map(
                (p: BurndownPoint) => `Day ${p.day}`,
              ),
              datasets: [
                {
                  label: "Ideal",
                  data: (sprintBurndown?.ideal_burndown || []).map(
                    (p: BurndownPoint) => p.ideal_remaining,
                  ),
                  borderColor: "rgba(255,99,132,0.8)",
                  backgroundColor: "rgba(255,99,132,0.1)",
                  borderDash: [5, 5],
                },
                {
                  label: "Actual",
                  data: (
                    sprintBurndown?.actual_burndown ||
                    sprintBurndown?.ideal_burndown ||
                    []
                  ).map((p: BurndownPoint) => p.remaining || p.ideal_remaining),
                  borderColor: "rgba(54,162,235,0.8)",
                  backgroundColor: "rgba(54,162,235,0.1)",
                },
              ],
            }}
            options={{
              responsive: true,
              maintainAspectRatio: false,
              plugins: { legend: { position: "top" } },
            }}
          />
        </Box>
      </Paper>

      {sprintCapacity && (
        <Paper sx={{ p: 2, mb: 2 }}>
          <Typography variant="h6" gutterBottom>
            Capacity
          </Typography>
          <Typography variant="body2" color="text.secondary" gutterBottom>
            Weeks: {sprintCapacity.weeks}, Capacity per person:{" "}
            {Math.round(sprintCapacity.capacity_hours_per_person * 10) / 10} h
          </Typography>
          <Box sx={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  <th style={{ textAlign: "left", padding: 8 }}>Assignee</th>
                  <th style={{ textAlign: "right", padding: 8 }}>Planned (h)</th>
                  <th style={{ textAlign: "right", padding: 8 }}>Capacity (h)</th>
                  <th style={{ textAlign: "right", padding: 8 }}>
                    Utilization %
                  </th>
                </tr>
              </thead>
              <tbody>
                {(sprintCapacity.assignees || []).map((r) => (
                  <tr key={r.assignee}>
                    <td style={{ padding: 8 }}>{r.assignee}</td>
                    <td style={{ textAlign: "right", padding: 8 }}>
                      {r.planned_hours}
                    </td>
                    <td style={{ textAlign: "right", padding: 8 }}>
                      {r.capacity_hours}
                    </td>
                    <td
                      style={{
                        textAlign: "right",
                        padding: 8,
                        color:
                          r.utilization_pct > 100
                            ? "#d32f2f"
                            : r.utilization_pct > 85
                              ? "#ed6c02"
                              : "inherit",
                      }}
                    >
                      {r.utilization_pct}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Box>
        </Paper>
      )}

      <Paper sx={{ p: 2 }}>
        <Typography variant="h6" gutterBottom>
          Quality
        </Typography>
        <Grid container spacing={2}>
          <Grid item xs={12} sm={4}>
            <Card>
              <CardContent>
                <Typography color="textSecondary" gutterBottom>
                  DoD
                </Typography>
                <Typography variant="h5">
                  {(sprintQuality?.dod_pct ?? 0).toFixed(1)}%
                </Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={12} sm={4}>
            <Card>
              <CardContent>
                <Typography color="textSecondary" gutterBottom>
                  Blockers
                </Typography>
                <Typography variant="h5">
                  {sprintQuality?.blockers ?? 0}
                </Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={12} sm={4}>
            <Card>
              <CardContent>
                <Typography color="textSecondary" gutterBottom>
                  Bugs by Priority
                </Typography>
                <Typography variant="body2">
                  {sprintQuality?.bugs_by_priority
                    ? Object.entries(sprintQuality.bugs_by_priority)
                        .map(([k, v]) => `${k}: ${v}`)
                        .join(" · ")
                    : "N/A"}
                </Typography>
              </CardContent>
            </Card>
          </Grid>
        </Grid>
      </Paper>
      </>
      )}
    </TabPanel>

    <TabPanel value={value} index={5}>
      <Paper sx={{ p: 2, mb: 2 }}>
        <Typography variant="h6" gutterBottom>
          Quality Thresholds
        </Typography>
        <Box display="flex" gap={2} alignItems="center" flexWrap="wrap" mb={1}>
          <TextField
            label="Min Line %"
            type="number"
            size="small"
            inputProps={{ step: 0.01, min: 0, max: 1 }}
            value={thresholds.min_line ?? ""}
            onChange={(event) =>
              setThresholds((t) => ({
                ...t,
                min_line: event.target.value === "" ? "" : Number(event.target.value),
              }))
            }
          />
          <TextField
            label="Min Branch %"
            type="number"
            size="small"
            inputProps={{ step: 0.01, min: 0, max: 1 }}
            value={thresholds.min_branch ?? ""}
            onChange={(event) =>
              setThresholds((t) => ({
                ...t,
                min_branch: event.target.value === "" ? "" : Number(event.target.value),
              }))
            }
          />
          <Button
            variant="contained"
            size="small"
            disabled={qualityLoading}
            onClick={() => void onSaveThresholds()}
          >
            Save
          </Button>
          <Button
            size="small"
            onClick={() => setThresholds({ min_line: 0.8, min_branch: 0.7 })}
          >
            Normal
          </Button>
          <Button
            size="small"
            onClick={() => setThresholds({ min_line: 0.9, min_branch: 0.8 })}
          >
            Strict
          </Button>
          <Button
            size="small"
            onClick={() => setThresholds({ min_line: 0.7, min_branch: 0.6 })}
          >
            Lenient
          </Button>
        </Box>
        <Box>
          <Typography variant="subtitle2" gutterBottom>
            Gate History (last 20)
          </Typography>
          <Box height={220}>
            <Line
              data={{
                labels: (hist || []).map((h) =>
                  new Date(h.created_at ?? h.checked_at ?? "").toLocaleDateString(),
                ),
                datasets: [
                  {
                    label: "Pass",
                    data: (hist || []).map((h) => ((h.passed ?? h.pass) ? 1 : 0)),
                    borderColor: "rgba(76,175,80,0.9)",
                    backgroundColor: "rgba(76,175,80,0.2)",
                  },
                ],
              }}
              options={{
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                  y: {
                    min: 0,
                    max: 1,
                    ticks: { callback: (v) => (v ? "PASS" : "FAIL") },
                  },
                },
                plugins: { legend: { display: false } },
              }}
            />
          </Box>
        </Box>
        <Box display="flex" gap={3} alignItems="center" mt={2}>
          <Box>
            <Typography variant="subtitle2">
              Project Quality Score
            </Typography>
            <Typography variant="h5">
              {(() => {
                const n = hist.length;
                if (!n) return "N/A";
                const passRatio =
                  hist.reduce((a, h) => a + ((h.passed ?? h.pass) ? 1 : 0), 0) / n;
                const avgCov =
                  hist
                    .map((h) => h.line_coverage ?? 1)
                    .reduce((a, b) => a + b, 0) / n;
                const score = Math.round(passRatio * (avgCov || 1) * 1000) / 10;
                return `${score}`;
              })()}
              %
            </Typography>
          </Box>
          <Box>
            <Typography variant="subtitle2">Actions</Typography>
            <Button
              size="small"
              variant="outlined"
              onClick={() => window.open("/quality", "_blank")}
            >
              Open Quality Page
            </Button>
            <Button
              size="small"
              variant="contained"
              sx={{ ml: 1 }}
              disabled={bulkProgress.active}
              onClick={() => void onBulkCheck()}
            >
              Check All PRs
            </Button>
            {bulkProgress.active && (
              <Box sx={{ display: "inline-block", ml: 2 }}>
                <CircularProgressWithLabel
                  value={bulkProgress.percent}
                  label={bulkProgress.step}
                  size={40}
                />
              </Box>
            )}
          </Box>
        </Box>
      </Paper>
    </TabPanel>

    <TabPanel value={value} index={6}>
      <Paper sx={{ p: 2, mb: 2 }}>
        <Box
          display="flex"
          justifyContent="space-between"
          alignItems="center"
          flexWrap="wrap"
          gap={1}
        >
          <Typography variant="h6">Repositories</Typography>
          <Button variant="contained" size="small" onClick={onOpenRepoDialog}>
            Link Repository
          </Button>
        </Box>
        <Box mt={2} display="flex" gap={1} flexWrap="wrap">
          <Chip
            size="small"
            label={`GitHub: ${repoProviders.github ? "configured" : "not configured"}`}
            color={repoProviders.github ? "success" : "default"}
          />
          <Chip
            size="small"
            label={`GitLab: ${repoProviders.gitlab ? "configured" : "not configured"}`}
            color={repoProviders.gitlab ? "success" : "default"}
          />
        </Box>
        {!repoProviders.github && !repoProviders.gitlab && (
          <Alert severity="info" sx={{ mt: 2 }}>
            Configure GitHub or GitLab integration in Settings to link repositories.
          </Alert>
        )}
        {repoLoading && <LinearProgress sx={{ mt: 2 }} />}
        <Table size="small" sx={{ mt: 2 }}>
          <TableHead>
            <TableRow>
              <TableCell>Provider</TableCell>
              <TableCell>Repository</TableCell>
              <TableCell>Primary</TableCell>
              <TableCell align="right">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {repoBindings.map((binding) => (
              <TableRow key={binding.id}>
                <TableCell width={120}>
                  <Chip
                    size="small"
                    color={binding.repository.provider === "gitlab" ? "primary" : "default"}
                    label={binding.repository.provider === "gitlab" ? "GitLab" : "GitHub"}
                  />
                </TableCell>
                <TableCell>
                  <Typography variant="body2" fontWeight={600}>
                    {binding.repository.repo_slug}
                  </Typography>
                  {binding.repository.default_branch && (
                    <Typography variant="caption" color="text.secondary">
                      Default branch: {binding.repository.default_branch}
                    </Typography>
                  )}
                </TableCell>
                <TableCell width={160}>
                  {binding.is_primary ? (
                    <Chip label="Primary" color="success" size="small" />
                  ) : (
                    <Button
                      size="small"
                      onClick={() => void onSetPrimaryRepository(binding)}
                      disabled={repoAction?.type === "primary" && repoAction.id === binding.repository_id}
                    >
                      {repoAction?.type === "primary" && repoAction.id === binding.repository_id
                        ? "Updating..."
                        : "Set Primary"}
                    </Button>
                  )}
                </TableCell>
                <TableCell align="right" width={140}>
                  <Button
                    size="small"
                    color="error"
                    onClick={() => void onRemoveRepository(binding)}
                    disabled={repoAction?.type === "remove" && repoAction.id === binding.repository_id}
                  >
                    {repoAction?.type === "remove" && repoAction.id === binding.repository_id
                      ? "Removing..."
                      : "Remove"}
                  </Button>
                </TableCell>
              </TableRow>
            ))}
            {!repoLoading && repoBindings.length === 0 && (
              <TableRow>
                <TableCell colSpan={4}>
                  <Typography variant="body2" color="text.secondary">
                    No repositories linked yet.
                  </Typography>
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </Paper>
    </TabPanel>
  </Paper>
);

export default ProjectDetailTabs;
