import { API_BASE_URL } from './api';

const API_URL = `${API_BASE_URL}/jira-fields`;

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
  const response = await fetch(`${API_URL}/fields?force_refresh=${forceRefresh}`);
  if (!response.ok) {
    throw new Error(`Failed to discover fields: ${response.statusText}`);
  }
  return response.json();
}

// Calibrate field mappings by analyzing sample issues
export async function calibrateFields(projectKey: string, sampleSize: number = 10): Promise<CalibrationResult> {
  const response = await fetch(`${API_URL}/calibrate?project_key=${projectKey}&sample_size=${sampleSize}`, {
    method: 'POST',
  });
  if (!response.ok) {
    throw new Error(`Failed to calibrate fields: ${response.statusText}`);
  }
  return response.json();
}

// Get current field mappings
export async function getFieldMappings(projectKey?: string, activeOnly: boolean = true): Promise<FieldMapping[]> {
  let url = `${API_URL}/mappings?active_only=${activeOnly}`;
  if (projectKey) {
    url += `&project_key=${projectKey}`;
  }
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to get field mappings: ${response.statusText}`);
  }
  return response.json();
}

// Save a field mapping
export async function saveFieldMapping(
  fieldType: string,
  fieldId: string,
  projectKey?: string
): Promise<{ field_type: string; field_id: string; status: string }> {
  const params = new URLSearchParams({ field_type: fieldType, field_id: fieldId });
  if (projectKey) {
    params.append('project_key', projectKey);
  }

  const response = await fetch(`${API_URL}/mappings?${params}`, {
    method: 'POST',
  });
  if (!response.ok) {
    throw new Error(`Failed to save field mapping: ${response.statusText}`);
  }
  return response.json();
}

// Delete/deactivate a field mapping
export async function deleteFieldMapping(mappingId: number): Promise<{ status: string; mapping_id: number }> {
  const response = await fetch(`${API_URL}/mappings/${mappingId}`, {
    method: 'DELETE',
  });
  if (!response.ok) {
    throw new Error(`Failed to delete field mapping: ${response.statusText}`);
  }
  return response.json();
}

// Test field mapping with a specific issue
export async function testFieldMapping(issueKey: string, fieldType?: string): Promise<TestMappingResult> {
  let url = `${API_URL}/test-mapping?issue_key=${issueKey}`;
  if (fieldType) {
    url += `&field_type=${fieldType}`;
  }

  const response = await fetch(url, {
    method: 'POST',
  });
  if (!response.ok) {
    throw new Error(`Failed to test field mapping: ${response.statusText}`);
  }
  return response.json();
}

// Export current configuration
export async function exportConfiguration(): Promise<JiraFieldConfiguration> {
  const response = await fetch(`${API_URL}/export-config`);
  if (!response.ok) {
    throw new Error(`Failed to export configuration: ${response.statusText}`);
  }
  return response.json();
}

// Import configuration
export async function importConfiguration(config: JiraFieldConfiguration): Promise<{ status: string; mappings_count: number }> {
  const response = await fetch(`${API_URL}/import-config`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(config),
  });
  if (!response.ok) {
    throw new Error(`Failed to import configuration: ${response.statusText}`);
  }
  return response.json();
}

// Get sprints for an issue using fallback strategies
export async function getIssueSprints(issueKey: string): Promise<{
  issue_key: string;
  sprints: JiraSprint[];
  sprint_count: number;
  active_sprint: JiraSprint | null;
}> {
  const response = await fetch(`${API_URL}/sprints/${issueKey}`);
  if (!response.ok) {
    throw new Error(`Failed to get issue sprints: ${response.statusText}`);
  }
  return response.json();
}
