import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { ArrowLeft, RefreshCw, CheckCircle, Brain, Zap, Shield, Clock } from 'lucide-react';
import { getIncident, rollbackIncident, type Incident } from '../utils/api';
import { motion } from 'framer-motion';

export function IncidentDetail() {
  const { id } = useParams<{ id: string }>();
  const [incident, setIncident] = useState<Incident | null>(null);
  const [loading, setLoading] = useState(true);
  const [rollingBack, setRollingBack] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (id) {
      fetchIncident(id);
    }
  }, [id]);

  const fetchIncident = async (incidentId: string) => {
    try {
      setLoading(true);
      setError(null);
      const data = await getIncident(incidentId);
      setIncident(data);
    } catch (err) {
      setError('Incident not found');
      console.error('Error fetching incident:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleRollback = async () => {
    if (!incident) return;
    try {
      setRollingBack(true);
      await rollbackIncident(incident.incident_id);
      await fetchIncident(incident.incident_id);
    } catch (err) {
      console.error('Rollback failed:', err);
    } finally {
      setRollingBack(false);
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-500"></div>
      </div>
    );
  }

  if (error || !incident) {
    return (
      <div className="bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-900 rounded-xl p-8 text-center">
        <p className="text-red-600 dark:text-red-400">{error || 'Incident not found'}</p>
        <Link to="/" className="mt-4 inline-block text-primary-500 hover:underline">
          ← Back to Dashboard
        </Link>
      </div>
    );
  }

  const severityConfig = {
    P0: { label: 'Critical', color: 'text-severity-critical border-severity-critical bg-red-50 dark:bg-red-950/20' },
    P1: { label: 'High', color: 'text-severity-high border-severity-high bg-orange-50 dark:bg-orange-950/20' },
    P2: { label: 'Medium', color: 'text-severity-medium border-severity-medium bg-yellow-50 dark:bg-yellow-950/20' },
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="space-y-6"
    >
      {/* Header */}
      <div className="flex items-center gap-4 flex-wrap">
        <Link to="/" className="text-gray-500 dark:text-dark-muted hover:text-primary-500 transition">
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <h1 className="text-2xl font-bold dark:text-dark-text">Incident Details</h1>
        <span className={`px-3 py-1 rounded-full text-sm font-medium border ${severityConfig[incident.severity as keyof typeof severityConfig]?.color || 'bg-gray-100 text-gray-800'}`}>
          {severityConfig[incident.severity as keyof typeof severityConfig]?.label || incident.severity}
        </span>
        <span className={`px-3 py-1 rounded-full text-sm font-medium ${
          incident.status === 'active' 
            ? 'bg-red-100 dark:bg-red-950/30 text-red-700 dark:text-red-400 border border-red-200 dark:border-red-900' 
            : 'bg-green-100 dark:bg-green-950/30 text-green-700 dark:text-green-400 border border-green-200 dark:border-green-900'
        }`}>
          {incident.status === 'active' ? (
            <span className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-severity-critical animate-pulse"></span>
              Active
            </span>
          ) : (
            'Resolved'
          )}
        </span>
        <span className="text-sm text-gray-400 dark:text-dark-muted ml-auto">
          {new Date(incident.declared_at).toLocaleString()}
        </span>
      </div>

      {/* Main Content */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column - Incident Info */}
        <div className="lg:col-span-2 space-y-6">
          {/* Title & Description */}
          <div className="bg-white dark:bg-dark-surface rounded-xl shadow-lg p-6">
            <h2 className="text-xl font-semibold dark:text-dark-text">{incident.title}</h2>
            <p className="text-gray-600 dark:text-dark-muted mt-2">{incident.description}</p>
            <div className="mt-3 flex items-center gap-4 text-sm text-gray-500 dark:text-dark-muted">
              <span>Service: <strong className="text-gray-700 dark:text-dark-text">{incident.service_name}</strong></span>
              <span>•</span>
              <span>ID: <code className="text-xs bg-gray-100 dark:bg-dark-border px-2 py-0.5 rounded">{incident.incident_id}</code></span>
            </div>
          </div>

          {/* Stack Trace */}
          {incident.stack_trace && (
            <div className="bg-white dark:bg-dark-surface rounded-xl shadow-lg overflow-hidden">
              <div className="bg-gray-900 px-4 py-2 flex items-center justify-between">
                <span className="text-sm text-gray-400 font-mono">Stack Trace</span>
                <span className="text-xs text-gray-600">Java</span>
              </div>
              <pre className="p-4 bg-gray-950 text-gray-300 text-xs overflow-x-auto max-h-64 font-mono leading-relaxed">
                {incident.stack_trace}
              </pre>
            </div>
          )}

          {/* AI Analysis Card */}
          <div className="bg-gradient-to-r from-primary-50 to-purple-50 dark:from-primary-950/20 dark:to-purple-950/20 border border-primary-200 dark:border-primary-800 rounded-xl shadow-lg p-6">
            <div className="flex items-center gap-2 mb-3">
              <Brain className="w-5 h-5 text-primary-500" />
              <h3 className="text-sm font-semibold text-primary-700 dark:text-primary-400">AI Analysis</h3>
              <span className="text-xs bg-primary-200 dark:bg-primary-800 text-primary-700 dark:text-primary-300 px-2 py-0.5 rounded-full ml-auto">
                Confidence {(incident.confidence_score * 100).toFixed(0)}%
              </span>
            </div>

            <div className="space-y-4">
              <div>
                <p className="text-xs font-medium text-primary-600 dark:text-primary-400 uppercase tracking-wider">Root Cause</p>
                <p className="text-gray-800 dark:text-dark-text bg-white/60 dark:bg-dark-bg/60 p-3 rounded-lg mt-1">
                  {incident.root_cause || 'Analysis in progress...'}
                </p>
              </div>

              <div>
                <p className="text-xs font-medium text-primary-600 dark:text-primary-400 uppercase tracking-wider">Suggested Fix</p>
                <p className="text-gray-800 dark:text-dark-text bg-white/60 dark:bg-dark-bg/60 p-3 rounded-lg mt-1 border-l-4 border-green-500">
                  {incident.suggested_fix || 'No fix suggested yet'}
                </p>
              </div>

              <div>
                <p className="text-xs font-medium text-primary-600 dark:text-primary-400 uppercase tracking-wider">Rollback Command</p>
                <pre className="bg-gray-900 text-green-400 p-3 rounded-lg mt-1 text-sm overflow-x-auto font-mono">
                  {incident.rollback_command || 'kubectl rollout undo deployment'}
                </pre>
              </div>
            </div>

            {/* Confidence Bar */}
            <div className="mt-4">
              <div className="flex justify-between text-xs text-gray-500 dark:text-dark-muted mb-1">
                <span>Confidence Score</span>
                <span>{(incident.confidence_score * 100).toFixed(0)}%</span>
              </div>
              <div className="h-2 bg-gray-200 dark:bg-dark-border rounded-full overflow-hidden">
                <motion.div
                  initial={{ width: 0 }}
                  animate={{ width: `${(incident.confidence_score * 100).toFixed(0)}%` }}
                  transition={{ duration: 1, ease: "easeOut" }}
                  className={`h-full rounded-full ${
                    incident.confidence_score > 0.8 ? 'bg-green-500' :
                    incident.confidence_score > 0.6 ? 'bg-yellow-500' : 'bg-red-500'
                  }`}
                />
              </div>
            </div>
          </div>
        </div>

        {/* Right Column - Actions & Metadata */}
        <div className="space-y-6">
          {/* Action Buttons */}
          {incident.status === 'active' && (
            <div className="bg-white dark:bg-dark-surface rounded-xl shadow-lg p-6">
              <h3 className="text-sm font-semibold text-gray-700 dark:text-dark-text mb-4">Actions</h3>
              <button
                onClick={handleRollback}
                disabled={rollingBack}
                className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-red-600 hover:bg-red-700 text-white rounded-lg transition disabled:opacity-50 shadow-lg shadow-red-600/20"
              >
                {rollingBack ? (
                  <RefreshCw className="w-5 h-5 animate-spin" />
                ) : (
                  <Zap className="w-5 h-5" />
                )}
                {rollingBack ? 'Rolling Back...' : 'Rollback Now'}
              </button>
              <p className="text-xs text-gray-400 dark:text-dark-muted mt-2 text-center">
                This will revert the last deployment
              </p>
            </div>
          )}

          {/* Metadata */}
          <div className="bg-white dark:bg-dark-surface rounded-xl shadow-lg p-6">
            <h3 className="text-sm font-semibold text-gray-700 dark:text-dark-text mb-4">Metadata</h3>
            <div className="space-y-3 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-500 dark:text-dark-muted">Incident ID</span>
                <code className="text-gray-700 dark:text-dark-text font-mono text-xs">{incident.incident_id}</code>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500 dark:text-dark-muted">Service</span>
                <span className="text-gray-700 dark:text-dark-text">{incident.service_name}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500 dark:text-dark-muted">Severity</span>
                <span className={`font-semibold ${
                  incident.severity === 'P0' ? 'text-severity-critical' :
                  incident.severity === 'P1' ? 'text-severity-high' :
                  'text-severity-medium'
                }`}>{incident.severity}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500 dark:text-dark-muted">Status</span>
                <span className={incident.status === 'active' ? 'text-severity-critical' : 'text-green-500'}>
                  {incident.status}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500 dark:text-dark-muted">Confidence</span>
                <span>{(incident.confidence_score * 100).toFixed(0)}%</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500 dark:text-dark-muted">Affected</span>
                <span>{incident.affected_services?.length || 0} services</span>
              </div>
            </div>
          </div>

          {/* Affected Services */}
          {incident.affected_services && incident.affected_services.length > 0 && (
            <div className="bg-white dark:bg-dark-surface rounded-xl shadow-lg p-6">
              <h3 className="text-sm font-semibold text-gray-700 dark:text-dark-text mb-3">Affected Services</h3>
              <div className="flex flex-wrap gap-2">
                {incident.affected_services.map((service) => (
                  <span
                    key={service}
                    className="px-3 py-1 bg-red-50 dark:bg-red-950/30 text-red-700 dark:text-red-400 text-xs rounded-full border border-red-200 dark:border-red-900"
                  >
                    {service}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </motion.div>
  );
}