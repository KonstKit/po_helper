import api from './api';

const API_URL = '/v1/jira-fields';

/** Jira field schema structure */
export interface JiraFieldSchema {
  type?: string;
  system?: string;
  custom?: string;
  customId?: number;
  items?: string;
}

/** Sprint data from Jira */
export interface JiraSprint {
  id: number;
  name: string;
  state?: 'active' | 'future' | 'closed' | string;
  startDate?: string;
  endDate?: string;
  completeDate?: string;
  goal?: string;
}

/** Exported configuration structure */
export interface JiraFieldConfiguration {
  mappings: FieldMapping[];
  version?: string;
  exported_at?: string;
}

export interface JiraField {
  id: string;
  name: string;
  type?: string;
  custom: boolean;
  schema?: JiraFieldSchema;
}

export interface FieldMapping {
  id?: number;
  field_type: string;
  field_id: string;
  field_name?: string;
  jira_field_id?: string;
  jira_field_name?: string;
  confidence?: number;
  project_key?: string;
  discovery_method?: string;
  confidence_score?: number;
  is_active: boolean;
}

export interface CalibrationResult {
  project_key: string;
  sample_size: number;
  calibration_results: Record<string, {
    type: string;
    confidence: number;
  }>;
  auto_mapped: number;
  warning?: string;
}

export interface FieldDiscoveryResult {
  total_fields: number;
  custom_fields: number;
  standard_fields: number;
  mappings: Record<string, {
    field_id: string;
    field_name: string;
  }>;
  all_fields: Record<string, JiraField>;
}

export interface TestMappingResult {
  issue_key: string;
  mapped_fields: Record<string, unknown>;
  sprints: JiraSprint[];
  has_sprint_data: boolean;
}

// Discover all available fields from Jira
export async function discoverJiraFields(forceRefresh: boolean = false): Promise<FieldDiscoveryResult> {
  const { data } = await api.get(`${API_URL}/fields`, {
    params: { force_refresh: forceRefresh },
  });
  return data as FieldDiscoveryResult;
}

// Calibrate field mappings by analyzing sample issues
export async function calibrateFields(projectKey: string, sampleSize: number = 10): Promise<CalibrationResult> {
  const { data } = await api.post(`${API_URL}/calibrate`, undefined, {
    params: {
      project_key: projectKey,
      sample_size: sampleSize,
    },
  });
  return data as CalibrationResult;
}

// Get current field mappings
export async function getFieldMappings(projectKey?: string, activeOnly: boolean = true): Promise<FieldMapping[]> {
  const params: Record<string, unknown> = { active_only: activeOnly };
  if (projectKey) {
    params.project_key = projectKey;
  }
  const { data } = await api.get(`${API_URL}/mappings`, { params });
  return data as FieldMapping[];
}

// Save a field mapping
export async function saveFieldMapping(
  fieldType: string,
  fieldId: string,
  projectKey?: string
): Promise<{ field_type: string; field_id: string; status: string }> {
  const params: Record<string, unknown> = {
    field_type: fieldType,
    field_id: fieldId,
  };
  if (projectKey) {
    params.project_key = projectKey;
  }

  const { data } = await api.post(`${API_URL}/mappings`, undefined, {
    params,
  });
  return data as { field_type: string; field_id: string; status: string };
}

// Delete/deactivate a field mapping
export async function deleteFieldMapping(mappingId: number): Promise<{ status: string; mapping_id: number }> {
  const { data } = await api.delete(`${API_URL}/mappings/${mappingId}`);
  return data as { status: string; mapping_id: number };
}

// Test field mapping with a specific issue
export async function testFieldMapping(issueKey: string, fieldType?: string): Promise<TestMappingResult> {
  const params: Record<string, unknown> = { issue_key: issueKey };
  if (fieldType) {
    params.field_type = fieldType;
  }

  const { data } = await api.post(`${API_URL}/test-mapping`, undefined, {
    params,
  });
  return data as TestMappingResult;
}

// Export current configuration
export async function exportConfiguration(): Promise<JiraFieldConfiguration> {
  const { data } = await api.get(`${API_URL}/export-config`);
  return data as JiraFieldConfiguration;
}

// Import configuration
export async function importConfiguration(config: JiraFieldConfiguration): Promise<{ status: string; mappings_count: number }> {
  const { data } = await api.post(`${API_URL}/import-config`, config);
  return data as { status: string; mappings_count: number };
}

// Get sprints for an issue using fallback strategies
export async function getIssueSprints(issueKey: string): Promise<{
  issue_key: string;
  sprints: JiraSprint[];
  sprint_count: number;
  active_sprint: JiraSprint | null;
}> {
  const { data } = await api.get(`${API_URL}/sprints/${issueKey}`);
  return data as {
    issue_key: string;
    sprints: JiraSprint[];
    sprint_count: number;
    active_sprint: JiraSprint | null;
  };
}
