import axios, { AxiosError } from 'axios';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export const api = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 10000,
});

// Add response interceptor for error handling
api.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    // Normalize error messages
    if (error.code === 'ECONNABORTED') {
      throw new Error('Request timeout - backend might be slow or unavailable');
    }
    if (!error.response) {
      throw new Error('Network error - cannot reach backend');
    }
    const status = error.response.status;
    const data = error.response.data as any;
    const message = data?.detail || data?.message || error.message;
    
    if (status === 404) {
      throw new Error('Resource not found');
    }
    if (status === 500) {
      throw new Error('Server error - check backend logs');
    }
    throw new Error(message || `Request failed with status ${status}`);
  }
);

export type Incident = {
  id?: number;
  incident_id: string;
  service_name: string;
  severity: string;
  status: string;
  title: string;
  description: string;
  stack_trace?: string;
  root_cause: string;
  suggested_fix: string;
  rollback_command: string;
  confidence_score: number;
  declared_at: string;
  resolved_at?: string;
  affected_services: string[];
  extra_metadata?: {
    rag_context_used?: boolean;
    reported_by?: string;
    github?: {
      recent_prs?: Array<{
        number: number;
        title: string;
        author: string;
        url: string;
        merged_at: string;
        additions: number;
        deletions: number;
        files: string[];
      }>;
      blame?: {
        commit_hash: string;
        author: string;
        message: string;
        line: number;
        file: string;
        pr_number?: number;
        pr_title?: string;
        pr_url?: string;
        pr_author?: string;
      };
    };
    code_context?: {
      file_path: string;
      line_number: number;
      total_lines: number;
      code_snippet: string;
      full_file?: string;
    };
    auto_fix?: {
      original_code?: string;
      fixed_code?: string;
      diff?: string;
      explanation?: string;
      file_path?: string;
      line_number?: number;
      status?: string;
      approved?: boolean;
      requires_approval?: boolean;
      pr?: {
        status?: string;
        message?: string;
        fix_preview?: string;
        approval_url?: string;
        approval_required?: boolean;
      };
      fix?: string;
      rejected?: boolean;
      rejection_reason?: string;
      code_context?: {
        file_path?: string;
        line_number?: number;
        total_lines?: number;
        code_snippet?: string;
        full_file?: string;
      };
    };
  };
};

export type Service = {
  name: string;
  description: string;
  on_call: string[];
  dependencies: string[];
  is_critical: boolean;
  repo_name?: string;
};

export type OnCallPerson = {
  id: string | number;
  service_name: string;
  name: string;
  slack_handle: string;
  email?: string | null;
  phone?: string | null;
  role: string;
  is_active?: boolean;
};

export type PendingFix = {
  id: string;
  incident_id: string;
  title: string;
  file_path: string;
  line_number: number;
  fix_preview: string;
  diff: string;
  explanation: string;
  severity: string;
  created_at: string;
  requires_approval: boolean;
  status: string;
  service_name?: string;
};

export const isPendingAutoFix = (autoFix?: NonNullable<Incident['extra_metadata']>['auto_fix']) => {
  if (!autoFix) return false;
  const status = (autoFix.status || autoFix.pr?.status || '').toLowerCase();
  if (status === 'approved' || status === 'rejected' || status === 'pr_created' || autoFix.approved || autoFix.rejected) {
    return false;
  }
  return Boolean(
    autoFix.requires_approval ||
    autoFix.pr?.approval_required ||
    status === 'fix_generated' ||
    status === 'pr_draft' ||
    status === 'pending'
  );
};

// API functions
export const getIncidents = async () => {
  const response = await api.get('/api/v1/incidents');
  return response.data;
};

export const getIncident = async (id: string) => {
  const response = await api.get(`/api/v1/incident/${id}`);
  return response.data;
};

export const declareIncident = async (data: {
  service_name: string;
  message: string;
  stack_trace?: string;
}) => {
  const response = await api.post('/api/v1/incident/declare', data);
  return response.data;
};

export const rollbackIncident = async (incident_id: string) => {
  const response = await api.post('/api/v1/incident/rollback', { incident_id });
  return response.data;
};

export const getServices = async () => {
  const response = await api.get('/api/v1/services');
  return response.data;
};

export const seedServices = async () => {
  const response = await api.post('/api/v1/services/seed');
  return response.data;
};

export const createService = async (data: {
  name: string;
  description?: string;
  repo_name?: string;
  dependencies?: string[];
  is_critical?: boolean;
  on_call?: string[];
}) => {
  const response = await api.post('/api/v1/services', data);
  return response.data;
};

export const deleteService = async (name: string) => {
  const response = await api.delete(`/api/v1/services/${encodeURIComponent(name)}`);
  return response.data;
};

export const approveFix = async (incident_id: string) => {
  const response = await api.post(`/api/v1/incident/${incident_id}/approve`);
  return response.data;
};

export const rejectFix = async (incident_id: string, reason?: string) => {
  const response = await api.post(`/api/v1/incident/${incident_id}/reject`, { reason });
  return response.data;
};

export const getPendingFixes = async (): Promise<{ fixes: PendingFix[]; count: number }> => {
  const response = await api.get('/api/v1/fixes/pending');
  return response.data;
};

export const getOnCallRoster = async (serviceName?: string): Promise<{ roster: OnCallPerson[]; count: number }> => {
  const response = await api.get('/api/v1/oncall', {
    params: serviceName ? { service_name: serviceName } : undefined,
  });
  return response.data;
};

export const addOnCallMember = async (data: {
  name: string;
  email?: string;
  slack_handle?: string;
  phone?: string;
  role?: string;
  service_name: string;
}) => {
  const response = await api.post('/api/v1/oncall/members', data);
  return response.data;
};

export const removeOnCallMember = async (id: string | number) => {
  const response = await api.delete(`/api/v1/oncall/members/${id}`);
  return response.data;
};

export const sendOnCallAlert = async (data: {
  target?: string;
  everyone?: boolean;
  message?: string;
  incident_id?: string;
  service_name?: string;
}) => {
  const response = await api.post('/api/v1/oncall/alert', data);
  return response.data;
};
