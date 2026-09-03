import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { ArrowLeft, RefreshCw, Brain, Zap, GitCommit, GitPullRequest, Code, User, ThumbsUp, Clock, Activity, XCircle, Copy, AlertTriangle } from 'lucide-react';
import { getIncident, rollbackIncident, approveFix, rejectFix, isPendingAutoFix, type Incident } from '../utils/api';
import { motion } from 'framer-motion';

export function IncidentDetail() {
  const { id } = useParams<{ id: string }>();
  const [incident, setIncident] = useState<Incident | null>(null);
  const [loading, setLoading] = useState(true);
  const [rollingBack, setRollingBack] = useState(false);
  const [approvingFix, setApprovingFix] = useState(false);
  const [rejectingFix, setRejectingFix] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

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

  const applyAutoFixStatus = (status: 'approved' | 'rejected', extra?: Record<string, unknown>) => {
    setIncident((prev) => {
      if (!prev) return prev;
      const autoFix = { ...(prev.extra_metadata?.auto_fix || {}), ...(extra || {}), status, approved: status === 'approved', rejected: status === 'rejected', requires_approval: false };
      if (autoFix.pr) {
        autoFix.pr = { ...autoFix.pr, approval_required: false, status };
      }
      return {
        ...prev,
        extra_metadata: {
          ...prev.extra_metadata,
          auto_fix: autoFix,
        },
      };
    });
  };

  const handleApproveFix = async () => {
    if (!incident) return;
    try {
      setApprovingFix(true);
      setActionMessage(null);
      const result = await approveFix(incident.incident_id);
      applyAutoFixStatus('approved', result.auto_fix);
      setActionMessage(result.message || 'Fix approved');
      await fetchIncident(incident.incident_id);
    } catch (err) {
      console.error('Fix approval failed:', err);
      setActionMessage(err instanceof Error ? err.message : 'Fix approval failed');
    } finally {
      setApprovingFix(false);
    }
  };

  const handleRejectFix = async () => {
    if (!incident) return;
    try {
      setRejectingFix(true);
      setActionMessage(null);
      const result = await rejectFix(incident.incident_id);
      applyAutoFixStatus('rejected', result.auto_fix);
      setActionMessage(result.message || 'Fix rejected');
      await fetchIncident(incident.incident_id);
    } catch (err) {
      console.error('Fix rejection failed:', err);
      setActionMessage(err instanceof Error ? err.message : 'Fix rejection failed');
    } finally {
      setRejectingFix(false);
    }
  };

  const getSeverityConfig = (severity: string) => {
    switch (severity) {
      case 'P0': return { label: 'Critical', color: 'text-severity-critical border-severity-critical/30 bg-severity-critical/10' };
      case 'P1': return { label: 'High', color: 'text-severity-high border-severity-high/30 bg-severity-high/10' };
      case 'P2': return { label: 'Medium', color: 'text-severity-medium border-severity-medium/30 bg-severity-medium/10' };
      default: return { label: severity, color: 'text-light-muted dark:text-dark-muted border-light-border dark:border-dark-border bg-light-surface dark:bg-dark-surface' };
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="text-center">
          <RefreshCw className="w-8 h-8 text-brand-primary animate-spin mx-auto" />
          <p className="mt-4 text-light-muted dark:text-dark-muted">Loading incident details...</p>
        </div>
      </div>
    );
  }

  if (error || !incident) {
    return (
      <div className="bg-severity-critical/10 border border-severity-critical/30 rounded-2xl p-8 text-center">
        <AlertTriangle className="w-12 h-12 text-severity-critical mx-auto mb-3" />
        <p className="text-severity-critical">{error || 'Incident not found'}</p>
        <Link to="/" className="mt-4 inline-block text-brand-primary hover:underline">
          ← Back to Dashboard
        </Link>
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="space-y-6"
    >
      {/* Header */}
      <div className="flex items-center gap-4 flex-wrap">
        <Link to="/" className="text-light-muted dark:text-dark-muted hover:text-brand-primary transition">
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <div className="flex-1">
          <h1 className="text-2xl font-bold text-light-text dark:text-dark-text">Incident Details</h1>
          <p className="text-sm text-light-muted dark:text-dark-muted">{incident.incident_id}</p>
        </div>
        <div className="flex items-center gap-2">
          <span className={`px-3 py-1 rounded-full text-sm font-medium border ${getSeverityConfig(incident.severity).color}`}>
            {getSeverityConfig(incident.severity).label}
          </span>
          <span className={`px-3 py-1 rounded-full text-sm font-medium ${
            incident.status === 'active' 
              ? 'bg-severity-critical/20 text-severity-critical border border-severity-critical/30' 
              : 'bg-brand-success/20 text-brand-success border border-brand-success/30'
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
        </div>
      </div>

      {/* Main Content Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column - Main Info */}
        <div className="lg:col-span-2 space-y-6">
          {/* Title & Description */}
          <div className="bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border shadow-lg p-6">
            <h2 className="text-xl font-semibold text-light-text dark:text-dark-text mb-2">{incident.title}</h2>
            <p className="text-light-muted dark:text-dark-muted mb-4">{incident.description}</p>
            <div className="flex items-center gap-4 text-sm text-light-muted dark:text-dark-muted">
              <span>Service: <strong className="text-light-text dark:text-dark-text">{incident.service_name}</strong></span>
              <span>•</span>
              <span>Declared: {new Date(incident.declared_at).toLocaleString()}</span>
            </div>
          </div>

          {/* Stack Trace */}
          {incident.stack_trace && (
            <div className="bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border shadow-lg overflow-hidden">
              <div className="bg-light-bg dark:bg-dark-bg px-4 py-2 flex items-center justify-between border-b border-light-border dark:border-dark-border">
                <span className="text-sm text-light-muted dark:text-dark-muted font-mono">Stack Trace</span>
                <span className="text-xs text-light-muted dark:text-dark-muted">Java</span>
              </div>
              <pre className="p-4 bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text text-xs overflow-x-auto max-h-64 font-mono leading-relaxed">
                {incident.stack_trace}
              </pre>
            </div>
          )}

          {/* AI Analysis Card - The "Wow" Card */}
          <div className="bg-gradient-to-br from-brand-primary/10 to-brand-secondary/10 border border-brand-primary/20 rounded-2xl shadow-lg p-6">
            <div className="flex items-center gap-2 mb-4">
              <Brain className="w-5 h-5 text-brand-primary" />
              <h3 className="text-sm font-semibold text-brand-primary">AI Analysis</h3>
              <span className="text-xs bg-brand-primary/20 text-brand-primary px-2 py-0.5 rounded-full ml-auto">
                {(incident.confidence_score * 100).toFixed(0)}% confidence
              </span>
            </div>

            <div className="space-y-4">
              <div>
                <p className="text-xs font-medium text-brand-primary uppercase tracking-wider mb-1">Root Cause</p>
                <p className="text-light-text dark:text-dark-text bg-light-card dark:bg-dark-card p-3 rounded-lg border border-light-border dark:border-dark-border">
                  {incident.root_cause}
                </p>
              </div>

              <div>
                <p className="text-xs font-medium text-brand-primary uppercase tracking-wider mb-1">Suggested Fix</p>
                <p className="text-light-text dark:text-dark-text bg-light-card dark:bg-dark-card p-3 rounded-lg border-l-4 border-brand-success">
                  {incident.suggested_fix}
                </p>
              </div>

              <div>
                <p className="text-xs font-medium text-brand-primary uppercase tracking-wider mb-1">Rollback Command</p>
                <div className="relative">
                  <pre className="bg-light-bg dark:bg-dark-bg text-brand-success p-3 rounded-lg text-sm overflow-x-auto font-mono">
                    {incident.rollback_command}
                  </pre>
                  <button
                    onClick={() => navigator.clipboard.writeText(incident.rollback_command)}
                    className="absolute top-2 right-2 p-1.5 bg-light-surface dark:bg-dark-surface rounded hover:bg-light-border dark:hover:bg-dark-border transition"
                  >
                    <Copy className="w-4 h-4 text-light-muted dark:text-dark-muted" />
                  </button>
                </div>
              </div>
            </div>

            {/* Confidence Bar */}
            <div className="mt-4">
              <div className="flex justify-between text-xs text-light-muted dark:text-dark-muted mb-1">
                <span>Confidence Score</span>
                <span>{(incident.confidence_score * 100).toFixed(0)}%</span>
              </div>
              <div className="h-2 bg-light-border dark:bg-dark-border rounded-full overflow-hidden">
                <motion.div
                  initial={{ width: 0 }}
                  animate={{ width: `${(incident.confidence_score * 100).toFixed(0)}%` }}
                  transition={{ duration: 1, ease: "easeOut" }}
                  className={`h-full rounded-full ${
                    incident.confidence_score > 0.8 ? 'bg-brand-success' :
                    incident.confidence_score > 0.6 ? 'bg-brand-warning' : 'bg-severity-critical'
                  }`}
                />
              </div>
            </div>
          </div>

          {/* Code Context - VS Code-like dark theme */}
          {(incident.extra_metadata?.code_context || incident.extra_metadata?.auto_fix?.code_context) && (
            <div className="bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border shadow-lg overflow-hidden">
              <div className="bg-light-bg dark:bg-dark-bg px-4 py-2 flex items-center justify-between border-b border-light-border dark:border-dark-border">
                <div className="flex items-center gap-2">
                  <Code className="w-4 h-4 text-brand-primary" />
                  <span className="text-sm text-light-muted dark:text-dark-muted font-mono">Code Context</span>
                </div>
                <span className="text-xs text-light-muted dark:text-dark-muted">
                  {incident.extra_metadata?.code_context?.file_path || incident.extra_metadata?.auto_fix?.code_context?.file_path || 'unknown'}:
                  {incident.extra_metadata?.code_context?.line_number || incident.extra_metadata?.auto_fix?.code_context?.line_number || 0}
                </span>
              </div>
              <pre className="p-4 bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text text-xs overflow-x-auto max-h-64 font-mono leading-relaxed">
                {incident.extra_metadata?.code_context?.code_snippet || incident.extra_metadata?.auto_fix?.code_context?.code_snippet || 'No code context available'}
              </pre>
            </div>
          )}

          {/* Git Blame Card - Author avatar, commit, PR */}
          {incident.extra_metadata?.github?.blame && (
            <div className="bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border shadow-lg p-6">
              <div className="flex items-center gap-2 mb-4">
                <GitCommit className="w-5 h-5 text-brand-warning" />
                <h3 className="text-sm font-semibold text-brand-warning">Git Blame</h3>
              </div>
              <div className="space-y-4">
                <div className="flex items-center gap-4">
                  <div className="w-12 h-12 rounded-full bg-brand-primary/20 flex items-center justify-center text-brand-primary font-bold text-lg">
                    {incident.extra_metadata.github.blame.author.charAt(0).toUpperCase()}
                  </div>
                  <div className="flex-1">
                    <p className="text-sm text-light-muted dark:text-dark-muted">Author</p>
                    <p className="text-sm font-medium text-light-text dark:text-dark-text">{incident.extra_metadata.github.blame.author}</p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <GitCommit className="w-4 h-4 text-light-muted dark:text-dark-muted" />
                  <div className="flex-1">
                    <p className="text-xs text-light-muted dark:text-dark-muted">Commit</p>
                    <code className="text-sm text-light-text dark:text-dark-text bg-light-surface dark:bg-dark-surface px-2 py-0.5 rounded">
                      {incident.extra_metadata.github.blame.commit_hash}
                    </code>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <Code className="w-4 h-4 text-light-muted dark:text-dark-muted" />
                  <div className="flex-1">
                    <p className="text-xs text-light-muted dark:text-dark-muted">File & Line</p>
                    <p className="text-sm text-light-text dark:text-dark-text">
                      {incident.extra_metadata.github.blame.file}:{incident.extra_metadata.github.blame.line}
                    </p>
                  </div>
                </div>
                <div className="flex items-start gap-3">
                  <User className="w-4 h-4 text-light-muted dark:text-dark-muted mt-0.5" />
                  <div className="flex-1">
                    <p className="text-xs text-light-muted dark:text-dark-muted">Commit Message</p>
                    <p className="text-sm text-light-text dark:text-dark-text italic">
                      {incident.extra_metadata.github.blame.message}
                    </p>
                  </div>
                </div>
                {incident.extra_metadata.github.blame.pr_number && (
                  <div className="flex items-center gap-3 pt-4 border-t border-light-border dark:border-dark-border">
                    <GitPullRequest className="w-4 h-4 text-brand-primary" />
                    <div className="flex-1">
                      <p className="text-xs text-light-muted dark:text-dark-muted">Associated PR</p>
                      <a
                        href={incident.extra_metadata.github.blame.pr_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-sm text-brand-primary hover:underline"
                      >
                        #{incident.extra_metadata.github.blame.pr_number}: {incident.extra_metadata.github.blame.pr_title}
                      </a>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Auto-Fix Preview - Diff view with approve/reject */}
          {incident.extra_metadata?.auto_fix && (
            <div className="bg-brand-success/10 border border-brand-success/20 rounded-2xl shadow-lg p-6">
              <div className="flex items-center gap-2 mb-4">
                <Zap className="w-5 h-5 text-brand-success" />
                <h3 className="text-sm font-semibold text-brand-success">Auto-Fix Preview</h3>
                {(incident.extra_metadata.auto_fix.status === 'approved' || incident.extra_metadata.auto_fix.approved) && (
                  <span className="text-xs bg-brand-success/20 text-brand-success px-2 py-0.5 rounded-full ml-auto">
                    Approved
                  </span>
                )}
                {(incident.extra_metadata.auto_fix.status === 'rejected' || incident.extra_metadata.auto_fix.rejected) && (
                  <span className="text-xs bg-severity-critical/20 text-severity-critical px-2 py-0.5 rounded-full ml-auto">
                    Rejected
                  </span>
                )}
              </div>
              <div className="space-y-4">
                <div>
                  <p className="text-xs font-medium text-brand-success uppercase tracking-wider mb-1">Explanation</p>
                  <p className="text-light-text dark:text-dark-text bg-light-card dark:bg-dark-card p-3 rounded-lg border border-light-border dark:border-dark-border">
                    {incident.extra_metadata.auto_fix.pr?.message || incident.extra_metadata.auto_fix.explanation || incident.extra_metadata.auto_fix.fix}
                  </p>
                </div>
                <div>
                  <p className="text-xs font-medium text-brand-success uppercase tracking-wider mb-1">Diff</p>
                  <pre className="bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text p-3 rounded-lg text-xs overflow-x-auto font-mono max-h-64 border border-light-border dark:border-dark-border">
                    {incident.extra_metadata.auto_fix.pr?.fix_preview || incident.extra_metadata.auto_fix.diff || incident.extra_metadata.auto_fix.fix}
                  </pre>
                </div>
                {(incident.extra_metadata.auto_fix.code_context?.code_snippet || incident.extra_metadata.auto_fix.fixed_code) && (
                  <div>
                    <p className="text-xs font-medium text-brand-success uppercase tracking-wider mb-1">Fixed Code</p>
                    <pre className="bg-light-bg dark:bg-dark-bg text-brand-success p-3 rounded-lg text-xs overflow-x-auto font-mono max-h-64 border border-light-border dark:border-dark-border">
                      {incident.extra_metadata.auto_fix.code_context?.code_snippet || incident.extra_metadata.auto_fix.fixed_code}
                    </pre>
                  </div>
                )}
                {actionMessage && (
                  <p className="text-sm text-light-text dark:text-dark-text bg-light-card dark:bg-dark-card p-3 rounded-lg border border-light-border dark:border-dark-border">
                    {actionMessage}
                  </p>
                )}
                {isPendingAutoFix(incident.extra_metadata.auto_fix) && (
                  <div className="flex gap-3">
                    <button
                      onClick={handleApproveFix}
                      disabled={approvingFix || rejectingFix}
                      className="flex-1 flex items-center justify-center gap-2 px-4 py-3 bg-brand-success hover:bg-brand-success/90 text-white rounded-lg transition disabled:opacity-50"
                    >
                      {approvingFix ? (
                        <>
                          <RefreshCw className="w-4 h-4 animate-spin" />
                          Approving...
                        </>
                      ) : (
                        <>
                          <ThumbsUp className="w-4 h-4" />
                          Approve Fix
                        </>
                      )}
                    </button>
                    <button
                      onClick={handleRejectFix}
                      disabled={approvingFix || rejectingFix}
                      className="flex-1 flex items-center justify-center gap-2 px-4 py-3 bg-severity-critical hover:bg-severity-critical/90 text-white rounded-lg transition disabled:opacity-50"
                    >
                      {rejectingFix ? (
                        <>
                          <RefreshCw className="w-4 h-4 animate-spin" />
                          Rejecting...
                        </>
                      ) : (
                        <>
                          <XCircle className="w-4 h-4" />
                          Reject Fix
                        </>
                      )}
                    </button>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Right Column - Actions & Metadata */}
        <div className="space-y-6">
          {/* Blast Radius Visualization */}
          {incident.affected_services && incident.affected_services.length > 0 && (
            <div className="bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border shadow-lg p-6">
              <div className="flex items-center gap-2 mb-4">
                <Activity className="w-5 h-5 text-brand-accent" />
                <h3 className="text-sm font-semibold text-brand-accent">Blast Radius</h3>
              </div>
              <div className="mb-4">
                <p className="text-xs text-light-muted dark:text-dark-muted mb-2">Affected Services</p>
                <div className="flex flex-wrap gap-2">
                  {incident.affected_services.map((service) => (
                    <motion.span
                      key={service}
                      initial={{ scale: 0 }}
                      animate={{ scale: 1 }}
                      className="px-3 py-1 bg-severity-critical/20 text-severity-critical text-xs rounded-full border border-severity-critical/30"
                    >
                      {service}
                    </motion.span>
                  ))}
                </div>
              </div>
              <div className="text-center py-4">
                <div className="text-3xl font-bold text-brand-accent">{incident.affected_services.length}</div>
                <div className="text-xs text-light-muted dark:text-dark-muted">Services Affected</div>
              </div>
            </div>
          )}

          {/* Action Timeline */}
          <div className="bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border shadow-lg p-6">
            <div className="flex items-center gap-2 mb-4">
              <Clock className="w-5 h-5 text-brand-primary" />
              <h3 className="text-sm font-semibold text-brand-primary">Action Timeline</h3>
            </div>
            <div className="space-y-3">
              <div className="flex items-start gap-3">
                <div className="w-2 h-2 rounded-full bg-brand-success mt-2"></div>
                <div className="flex-1">
                  <p className="text-sm text-light-text dark:text-dark-text">Incident Declared</p>
                  <p className="text-xs text-light-muted dark:text-dark-muted">{new Date(incident.declared_at).toLocaleString()}</p>
                </div>
              </div>
              {incident.status === 'resolved' && (
                <div className="flex items-start gap-3">
                  <div className="w-2 h-2 rounded-full bg-brand-success mt-2"></div>
                  <div className="flex-1">
                    <p className="text-sm text-light-text dark:text-dark-text">Incident Resolved</p>
                    <p className="text-xs text-light-muted dark:text-dark-muted">{incident.resolved_at ? new Date(incident.resolved_at).toLocaleString() : 'Recently'}</p>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Actions */}
          {incident.status === 'active' && (
            <div className="bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border shadow-lg p-6">
              <h3 className="text-sm font-semibold text-light-text dark:text-dark-text mb-4">Actions</h3>
              <button
                onClick={handleRollback}
                disabled={rollingBack}
                className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-severity-critical hover:bg-severity-critical/90 text-white rounded-lg transition disabled:opacity-50"
              >
                {rollingBack ? (
                  <>
                    <RefreshCw className="w-4 h-4 animate-spin" />
                    Rolling Back...
                  </>
                ) : (
                  <>
                    <Zap className="w-4 h-4" />
                    Rollback Now
                  </>
                )}
              </button>
              <p className="text-xs text-light-muted dark:text-dark-muted mt-2 text-center">
                This will revert the last deployment
              </p>
            </div>
          )}

          {/* Metadata */}
          <div className="bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border shadow-lg p-6">
            <h3 className="text-sm font-semibold text-light-text dark:text-dark-text mb-4">Metadata</h3>
            <div className="space-y-3 text-sm">
              <div className="flex justify-between">
                <span className="text-light-muted dark:text-dark-muted">Incident ID</span>
                <code className="text-light-text dark:text-dark-text font-mono text-xs">{incident.incident_id}</code>
              </div>
              <div className="flex justify-between">
                <span className="text-light-muted dark:text-dark-muted">Service</span>
                <span className="text-light-text dark:text-dark-text">{incident.service_name}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-light-muted dark:text-dark-muted">Severity</span>
                <span className={`font-semibold ${
                  incident.severity === 'P0' ? 'text-severity-critical' :
                  incident.severity === 'P1' ? 'text-severity-high' :
                  'text-severity-medium'
                }`}>{incident.severity}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-light-muted dark:text-dark-muted">Status</span>
                <span className={incident.status === 'active' ? 'text-severity-critical' : 'text-brand-success'}>
                  {incident.status}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-light-muted dark:text-dark-muted">Confidence</span>
                <span>{(incident.confidence_score * 100).toFixed(0)}%</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </motion.div>
  );
}