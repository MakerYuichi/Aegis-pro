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
  affected_services: string[];
  extra_metadata?: Record<string, any>;
};

export type Service = {
  name: string;
  description: string;
  on_call: string[];
  dependencies: string[];
  is_critical: boolean;
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
