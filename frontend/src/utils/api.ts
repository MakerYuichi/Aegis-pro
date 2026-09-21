import axios, { AxiosError } from 'axios';
import { useAuth0 } from '@auth0/auth0-react';
import { useMemo } from 'react';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export const api = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 60000,
  withCredentials: true, 
});

// Add response interceptor for error handling
api.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
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

export type BlastRadius = {
  root: string;
  affected: string[];
  count: number;
  severity: string;
};

export type Contributor = {
  username: string;
  role: 'author' | 'reviewer' | 'assignee' | 'committer';
  avatar?: string;
  url?: string;
};

export type GitBlame = {
  commit_hash: string;
  author: string;
  author_avatar?: string;
  message: string;
  line: number;
  file: string;
  pr_number?: number;
  pr_title?: string;
  pr_url?: string;
  pr_author?: string;
  contributors?: Contributor[];
};

export type CodeContext = {
  file_path: string;
  line_number: number;
  total_lines: number;
  code_snippet: string;
  full_file?: string;
};

export type AutoFix = {
  original_code?: string;
  fixed_code?: string;
  diff?: string;
  explanation?: string;
  file_path?: string;
  line_number?: number;
  status?: 'fix_generated' | 'pr_draft' | 'approved' | 'rejected' | 'pr_created';
  approved?: boolean;
  requires_approval?: boolean;
  rejected?: boolean;
  rejection_reason?: string;
  pr?: {
    status?: string;
    message?: string;
    fix_preview?: string;
    approval_url?: string;
    approval_required?: boolean;
    pr_number?: number;
    pr_url?: string;
    branch_name?: string;
    title?: string;
    body?: string;
  };
  fix?: string;
  code_context?: CodeContext;
};

export type GitHubMetadata = {
  recent_prs?: Array<{
    number: number;
    title: string;
    author: string;
    url: string;
    merged_at?: string;
  }>;
  related_prs?: Array<{
    sha?: string;
    commit_message?: string;
    commit_date?: string;
    number?: number;
    title?: string;
    author: string;
    url?: string;
    merged_at?: string;
    relevance_score?: number;
    reason?: string;
  }>;
  blame?: GitBlame;
};

export type Incident = {
  id?: number;
  incident_id: string;
  service_name: string;
  severity: string;
  status: string;
  title: string;
  description: string;
  stack_trace?: string;
  exception_type?: string;
  file_path?: string;
  line_number?: number;
  root_cause: string;
  suggested_fix: string;
  rollback_command: string;
  confidence_score: number;
  declared_at: string;
  resolved_at?: string;
  affected_services: string[];
  blast_radius?: BlastRadius;
  extra_metadata?: {
    rag_context_used?: boolean;
    reported_by?: string;
    github?: GitHubMetadata;
    code_context?: CodeContext;
    auto_fix?: AutoFix;
    demo_quality?: {
      confidence: 'high' | 'low' | 'fallback';
      real_file: boolean;
      category: string;
      blast_radius_reason: string;
      related_lines: number[];
    };
    demo_candidates?: DemoCandidate[];
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
  approved_by?: string;
  approved_at?: string;
  rejected_by?: string;
  rejected_at?: string;
};

export type OnCallMember = {
  id: number | string;
  service_name?: string;
  name: string;
  slack_handle: string;
  email?: string;
  phone?: string;
  role: string;
  is_active?: boolean;
};

export type Alert = {
  id: number;
  engineer: string;
  service: string;
  message: string;
  status: string;
  timestamp: string;
};

export type AlertRequest = {
  target?: string;
  everyone?: boolean;
  message?: string;
  incident_id?: string;
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

// API functions - Updated with 200 limit
export const getIncidents = async (limit: number = 200) => {
  const response = await api.get(`/api/v1/incidents?limit=${limit}`);
  return response.data;
};

export const getIncident = async (id: string) => {
  const response = await api.get(`/api/v1/incident/${id}`);
  return response.data;
};


export const getServices = async () => {
  const response = await api.get('/api/v1/services');
  return response.data;
};

export const getOnCallRoster = async (serviceName?: string): Promise<{ roster: OnCallMember[]; count: number }> => {
  const params = serviceName ? `?service_name=${serviceName}` : '';
  const response = await api.get(`/api/v1/oncall${params}`);
  return response.data;
};

export const getAlertHistory = async (limit: number = 20): Promise<{ alerts: Alert[]; count: number }> => {
  const response = await api.get(`/api/v1/oncall/alert/history?limit=${limit}`);
  return response.data;
};

export const getPendingFixes = async (): Promise<{ fixes: PendingFix[]; count: number }> => {
  const response = await api.get('/api/v1/fixes/pending');
  return response.data;
};

// ── Demo endpoints (public, no auth) ───────────────────────────────────

export type DemoParsed = {
  host: string;
  org: string;
  repo: string;
  language_hint: string;
};

export type DemoTimings = {
  try_check_ms?: number;
  parse_ms?: number;
  fetch_meta_ms?: number;
  fetch_tree_ms?: number;
  select_file_ms?: number;
  fetch_file_ms?: number;
  fetch_commits_ms?: number;
  fetch_contributors_ms?: number;
  fetch_prs_ms?: number;
  analyze_ms?: number;
  generate_ms?: number;
  total_ms: number;
};

export type DemoCandidate = {
  path: string;
  score: number;
  confidence: 'high' | 'low' | 'fallback';
};

export type DemoMeta = {
  tries_remaining: number;
  timings?: DemoTimings;
  was_free_switch?: boolean;
};

export type DemoGenerateResponse =
  | { incident: Incident; parsed: DemoParsed; meta: DemoMeta }
  | {
      error?: string;
      reason: string;
      detail: string;
      supported_shapes?: string[];
      signup_required?: boolean;
      tries_remaining?: number;
    };

export const getDemoDefault = async (): Promise<Incident> => {
  const response = await api.get('/api/v1/demo/default');
  return response.data;
};

export const generateDemoIncident = async (
  repo_url: string
): Promise<DemoGenerateResponse> => {
  const response = await api.post('/api/v1/demo/generate', { repo_url });
  return response.data;
};

export const regenerateDemoIncident = async (
  repo_url: string,
  file_path: string
): Promise<DemoGenerateResponse> => {
  const response = await api.post('/api/v1/demo/regenerate', {
    repo_url,
    file_path,
  });
  return response.data;
};

export const resetDemo = async (): Promise<{ status: string }> => {
  const response = await api.post('/api/v1/demo/reset');
  return response.data;
};

/**
 * Returns an axios instance wired with the current Auth0 access token.
 * Use for protected (mutating) endpoints only.
 */
export function useApiClient() {
  const { getAccessTokenSilently, isAuthenticated } = useAuth0();

  return useMemo(() => {
    const instance = axios.create({
      baseURL: API_URL,
      headers: { 'Content-Type': 'application/json' },
      timeout: 60000,
    });

    instance.interceptors.request.use(async (config) => {
      if (!isAuthenticated) {
        throw new Error('Not authenticated — cannot make API call');
      }
      try {
        const token = await getAccessTokenSilently({
          authorizationParams: {
            audience: import.meta.env.VITE_AUTH0_AUDIENCE,
          },
        });
        config.headers = config.headers || {};
        config.headers.Authorization = `Bearer ${token}`;
      } catch (err) {
        console.error('Failed to get Auth0 token:', err);
        throw new Error('Failed to obtain authentication token');
      }
      return config;
    });

    instance.interceptors.response.use(
      (response) => response,
      (error: AxiosError) => {
        if (error.code === 'ECONNABORTED') {
          throw new Error('Request timeout - backend might be slow or unavailable');
        }
        if (!error.response) {
          throw new Error('Network error - cannot reach backend');
        }
        const status = error.response.status;
        const data = error.response.data as any;
        const message = data?.detail || data?.message || error.message;

        if (status === 401) throw new Error('Unauthorized — please log in again');
        if (status === 403) throw new Error('Forbidden — you do not have access');
        if (status === 404) throw new Error('Resource not found');
        if (status === 500) throw new Error('Server error - check backend logs');
        throw new Error(message || `Request failed with status ${status}`);
      }
    );

    return instance;
  }, [getAccessTokenSilently, isAuthenticated]);
}

/**
 * Hook exposing all protected (mutating) API calls with auth.
 * Read-only calls stay on the module-level `api` export above.
 */
export function useProtectedApi() {
  const api = useApiClient();

  return useMemo(() => ({
    declareIncident: async (data: { service_name: string; message: string; stack_trace?: string }) => {
      const res = await api.post('/api/v1/incident/declare', data);
      return res.data;
    },
    rollbackIncident: async (incident_id: string) => {
      const res = await api.post('/api/v1/incident/rollback', { incident_id });
      return res.data;
    },
    approveFix: async (incident_id: string) => {
      const res = await api.post(`/api/v1/incident/${incident_id}/approve`);
      return res.data;
    },
    rejectFix: async (incident_id: string, reason?: string) => {
      const res = await api.post(`/api/v1/incident/${incident_id}/reject`, { reason });
      return res.data;
    },
    createService: async (data: {
      name: string;
      description?: string;
      repo_name?: string;
      dependencies?: string[];
      is_critical?: boolean;
      on_call?: string[];
    }) => {
      const res = await api.post('/api/v1/services', data);
      return res.data;
    },
    deleteService: async (name: string) => {
      const res = await api.delete(`/api/v1/services/${encodeURIComponent(name)}`);
      return res.data;
    },
    seedServices: async () => {
      const res = await api.post('/api/v1/services/seed');
      return res.data;
    },
    addOnCallMember: async (member: Partial<OnCallMember>) => {
      const res = await api.post('/api/v1/oncall/members', member);
      return res.data;
    },
    removeOnCallMember: async (memberId: number) => {
      const res = await api.delete(`/api/v1/oncall/members/${memberId}`);
      return res.data;
    },
    sendAlert: async (alert: AlertRequest) => {
      const res = await api.post('/api/v1/oncall/alert', alert);
      return res.data;
    },
    sendOnCallAlert: async (data: {
      target?: string;
      everyone?: boolean;
      message?: string;
      incident_id?: string;
      service_name?: string;
    }) => {
      const res = await api.post('/api/v1/oncall/alert', data);
      return res.data;
    },
  }), [api]);
}

