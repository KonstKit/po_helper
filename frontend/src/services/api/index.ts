/**
 * Centralized API exports - unified entry point for all API functions and types.
 *
 * This barrel file re-exports everything from domain modules, allowing clean imports:
 *   import { getProjects, getCurrentUser, Project } from '@/services/api';
 *
 * Module organization:
 * - client.ts       - Axios instance, interceptors, retry helper
 * - types.ts        - All TypeScript interfaces (~80 types)
 * - integrations.ts - JIRA, GitHub, GitLab, Bitbucket, Confluence, TestRail
 * - users.ts        - Current user operations
 * - projects.ts     - Project CRUD, repositories, analytics
 * - tasks.ts        - Task listing and operations
 * - quality.ts      - Defects, metrics, reports
 * - capacity.ts     - Team capacity, health checks, CFD
 * - testing.ts      - Flaky tests, coverage analysis
 * - traceability.ts - Matrix, chains, impact analysis
 * - knowledge.ts    - Confluence spaces, pages, ADRs
 * - sprints.ts      - Sprint listing, burndown, WIP
 * - analytics.ts    - Velocity, DORA, trends, quality gates
 */

// =============================================================================
// Client & Utilities
// =============================================================================
export { default as api } from './client';
export { API_BASE_URL, CACHE_TTL, withRetry } from './client';

// =============================================================================
// All Types
// =============================================================================
export * from './types';

// =============================================================================
// Domain APIs
// =============================================================================

// Integrations (JIRA, GitHub, GitLab, Bitbucket, Confluence, TestRail)
export {
  // JIRA
  getJiraSettings,
  putJiraSettings,
  putJiraSettings as updateJiraSettings,
  testJiraConnection,
  connectJira,
  listJiraProjects,
  type JiraProject,
  type JiraProjectsResponse,
  // GitHub
  getGithubSettings,
  getGithubSettings as getGitHubSettings,
  putGithubSettings,
  putGithubSettings as updateGitHubSettings,
  testGithubConnection,
  testGithubConnection as testGitHubConnection,
  // GitLab
  getGitlabSettings,
  getGitlabSettings as getGitLabSettings,
  putGitlabSettings,
  putGitlabSettings as updateGitLabSettings,
  testGitlabConnection,
  testGitlabConnection as testGitLabConnection,
  listGitlabProjects,
  // Bitbucket
  getBitbucketSettings,
  putBitbucketSettings,
  putBitbucketSettings as updateBitbucketSettings,
  testBitbucketConnection,
  // Bitbucket types
  type BitbucketSettings,
  type BitbucketTestResponse,
  // Confluence
  getConfluenceSettings,
  putConfluenceSettings,
  putConfluenceSettings as updateConfluenceSettings,
  testConfluenceConnection,
  // TestRail
  getTestrailSettings,
  getTestrailSettings as getTestRailSettings,
  putTestrailSettings,
  putTestrailSettings as updateTestRailSettings,
  testTestrailConnection,
  testTestrailConnection as testTestRailConnection,
  // Integration status
  getIntegrationsStatus,
  getIntegrationsStatus as getIntegrationStatus,
  clearIntegrationStatusCache,
  type IntegrationStatusResponse,
} from './integrations';

// Users, OAuth2 & MFA
export {
  getCurrentUser,
  updateCurrentUser,
  changePassword,
  loginWithPassword,
  // OAuth2 SSO
  getOAuth2Providers,
  startGoogleOAuth,
  startMicrosoftOAuth,
  googleOAuthCallback,
  microsoftOAuthCallback,
  // MFA
  getMFAStatus,
  initiateMFASetup,
  verifyMFASetup,
  disableMFA,
  regenerateBackupCodes,
  verifyMFALogin,
  // Types
  type OAuth2Providers,
  type OAuth2AuthURL,
  type OAuth2Token,
  type MFAStatus,
  type MFASetupResponse,
  type MFAVerifyResponse,
  type MFALoginResponse,
} from './users';

// Projects
export {
  listProjects,
  getProject,
  createProject,
  updateProject,
  deleteProject,
  purgeProject,
  getProjectRepositories,
  bindRepositoryToProject,
  unbindRepositoryFromProject,
  setPrimaryRepository,
  syncJiraProject,
} from './projects';

// Tasks
export {
  listTasks,
  listTasksPaginated,
  listTasksByProject,
  listTasksByProjectPaginated,
  getTask,
  setTaskBusinessValue,
  clearTasksCache,
} from './tasks';

// Quality (Defects, Metrics, Reports)
export {
  // Escaped Defects CRUD
  listEscapedDefects,
  getEscapedDefect,
  createEscapedDefect,
  updateEscapedDefect,
  deleteEscapedDefect,
  // Quality data
  getQualitySummary,
  getQualityDashboard,
  getQualityMetrics,
  getRootCauseAnalysis,
  getComponentAnalysis,
  getQualityTrend,
  calculateDefectMetrics,
  listDefectMetrics,
  // Reports
  generateQualityReport,
  downloadQualityReport,
  getQualityReportData,
  getQualityReportPreviewUrl,
} from './quality';

// Capacity
export {
  // Settings CRUD
  listCapacitySettings,
  getCapacitySetting,
  createCapacitySetting,
  updateCapacitySetting,
  deleteCapacitySetting,
  // Summary
  getTeamCapacitySummary,
  // Health checks
  listTeamHealthChecks,
  createTeamHealthCheck,
  getTeamHealthSummary,
  // CFD
  getCFDData,
  getFlowMetrics,
  takeCFDSnapshot,
} from './capacity';

// Testing (Flaky Tests, Coverage)
export {
  // Flaky tests
  listFlakyTests,
  getFlakyTest,
  createFlakyTest,
  updateFlakyTest,
  deleteFlakyTest,
  detectFlakyTests,
  getFlakyTestsSummary,
  // Coverage
  getCoverageFiles,
  getDeltaCoverage,
  getPRDeltaCoverage,
  calculateComponentCoverage,
  listComponentCoverage,
  getComponentCoverageSummary,
  getCoverageTrendAnalytics,
  listTestRuns,
  listTestResults,
  listCoverageReports,
  // Analytics
  getTestAnalyticsDashboard,
} from './testing';

// Traceability
export {
  // Matrix Summary (legacy)
  getTraceabilityMatrix,
  backfillTraceability,
  // RTM Matrix (full grid with pagination/filters)
  getRTMMatrix,
  queryRTMMatrix,
  // Matrix Configurations (saved projections)
  listMatrixConfigs,
  getMatrixConfig,
  createMatrixConfig,
  updateMatrixConfig,
  deleteMatrixConfig,
  applyMatrixConfig,
  // Requirement flow
  getTraceabilityRequirementFlow,
  // Task artifacts
  getTraceabilityTaskArtifacts,
  // GitHub pulls
  getGitHubProjectPulls,
  // Full chain
  getFullTraceabilityChain,
  // Impact analysis
  getImpactAnalysis,
  // Orphaned artifacts
  getOrphanedArtifacts,
  // Confidence scoring
  getConfidenceDistribution,
  recalculateLinkConfidence,
  // Suggested links
  generateSuggestedLinks,
  getSuggestedLinks,
  getSuggestedLinksStats,
  approveSuggestedLink,
  rejectSuggestedLink,
  bulkApproveSuggestedLinks,
  // Sync health
  getSyncHealth,
  getDetailedSyncHealth,
  // Consistency checks
  runConsistencyCheck,
  fixConsistencyIssues,
  getDetailedCycles,
  // Traceability Rules CRUD
  getRules,
  getRule,
  createRule,
  updateRule,
  deleteRule,
  executeRule,
  getRuleExecutions,
  getAllRuleExecutions,
  // Matrix Export
  createMatrixExport,
  getExportStatus,
  listExports,
  deleteExport,
  getExportDownloadUrl,
} from './traceability';

// Knowledge (Confluence)
export {
  // Spaces
  listConfluenceSpaces,
  // Pages
  listConfluencePages,
  listConfluencePagesLocal,
  getConfluencePage,
  // PRD
  getPrdRequirements,
  // Sync
  syncConfluence,
  getSpaceTree,
  syncSubtree,
  // ADR
  getADR,
  // Research
  getResearch,
  // Types
  type ConfluenceSpace,
  type ConfluenceSpacesResponse,
  type ConfluencePage,
  type ConfluencePagesResponse,
  type ConfluencePageDetail,
  type PrdRequirement,
  type PrdRequirementsResponse,
  type ConfluenceSyncResult,
  type SpaceTreeNode,
  type SpaceTreeResponse,
  type ADRResponse,
  type ResearchResponse,
} from './knowledge';

// Sprints
export {
  listSprints,
  getProjectSprints,
  getSprintBurndown,
  getSprintQuality,
  getSprintWipStatus,
  getSprintCapacity,
  getBoardsForProject,
  // Types
  type Sprint,
  type SprintsResponse,
  type SprintQuality,
  type SprintWipStatus,
  type SprintCapacity,
  type Board,
  type BoardsResponse,
} from './sprints';

// Analytics (Velocity, DORA, Trends, Quality Gates)
export {
  // Project analytics
  getVelocity,
  getBurndown,
  getRisks,
  getForecast,
  // DORA
  getDoraMetrics,
  // Team health
  getProjectTeamHealth,
  getProjectBudgetHours,
  getProjectValueMetrics,
  // Quality gates
  getQualityGateStatus,
  evaluateQualityGate,
  evaluateQualityGateAndCheck,
  getQualityHistory,
  // PR metrics
  getPRMetrics,
  listPullRequests,
  // Trends
  getTestTrend,
  getCoverageTrend,
  // Team analytics
  getTeamMembersActivity,
  // Health
  getIntegrationsHealth,
  getMetricsText,
  // Types
  type BudgetHoursResponse,
  type ValueMetricsResponse,
  type TestTrendResponse,
  type CoverageTrendResponse,
  type QualityGateEvaluatePayload,
  type QualityHistoryResponse,
} from './analytics';

// =============================================================================
// Default Export (for backward compatibility with `import api from '...'`)
// =============================================================================
import apiClient from './client';
export default apiClient;

// =============================================================================
// Backward-Compatible Aliases
// =============================================================================

// Projects - old function names
export { getProject as getProjectById } from './projects';

// Traceability - old function names
export { backfillTraceability as runTraceabilityBackfill } from './traceability';
