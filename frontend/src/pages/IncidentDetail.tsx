import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  ArrowLeft, RefreshCw, Brain, Zap, GitCommit, GitPullRequest, Code,
  Clock, Activity, Copy, AlertTriangle, ExternalLink, Users, GitMerge,
} from 'lucide-react';
import { getIncident, rollbackIncident, isPendingAutoFix, type Incident } from '../utils/api';
import { motion } from 'framer-motion';

export function IncidentDetail() {
  const { id } = useParams<{ id: string }>();
  const [incident, setIncident] = useState<Incident | null>(null);
  const [loading, setLoading] = useState(true);
  const [rollingBack, setRollingBack] = useState(false);
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
      setError(null);
      const result = await rollbackIncident(incident.incident_id);
      setActionMessage(result.message || 'Rollback initiated');
      await fetchIncident(incident.incident_id);
    } catch (err) {
      console.error('Rollback failed:', err);
      setError(err instanceof Error ? err.message : 'Rollback failed');
    } finally {
      setRollingBack(false);
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
            <div className="flex flex-wrap items-center gap-3 text-sm text-light-muted dark:text-dark-muted">
              <span>Service: <strong className="text-light-text dark:text-dark-text">{incident.service_name}</strong></span>
              <span>•</span>
              <span>Declared: {new Date(incident.declared_at).toLocaleString()}</span>
              {incident.extra_metadata?.reported_by && (
                <>
                  <span>•</span>
                  <span>Reported by: <strong className="text-light-text dark:text-dark-text">{incident.extra_metadata.reported_by}</strong></span>
                </>
              )}
              {incident.extra_metadata?.rag_context_used && (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-brand-secondary/10 text-brand-secondary border border-brand-secondary/25 rounded-full text-xs font-medium">
                  <Brain className="w-3 h-3" />
                  RAG context used
                </span>
              )}
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

          {/* Git Blame Card — author avatar, commit, PR, contributors */}
          {incident.extra_metadata?.github?.blame && (
            <div className="bg-gradient-to-br from-light-card to-light-surface dark:from-dark-card dark:to-dark-surface rounded-2xl border border-light-border dark:border-dark-border shadow-xl p-6 backdrop-blur-sm">
              <div className="flex items-center gap-2 mb-6">
                <GitCommit className="w-5 h-5 text-brand-warning" />
                <h3 className="text-sm font-semibold text-brand-warning">Git Blame</h3>
                {incident.extra_metadata?.github?.blame.pr_number && (
                  <a
                    href={incident.extra_metadata?.github?.blame.pr_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="ml-auto text-xs bg-brand-primary/20 text-brand-primary px-3 py-1 rounded-full hover:bg-brand-primary/30 transition"
                  >
                    View PR #{incident.extra_metadata?.github?.blame.pr_number}
                  </a>
                )}
              </div>
              <div className="space-y-5">
                <div className="flex items-center gap-4">
                  <a
                    href={`https://github.com/${incident.extra_metadata?.github?.blame?.author}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="relative group flex-shrink-0"
                  >
                    <img
                      src={`https://github.com/${incident.extra_metadata?.github?.blame?.author}.png`}
                      alt={incident.extra_metadata?.github?.blame?.author}
                      className="w-14 h-14 rounded-full border-2 border-brand-primary/30 group-hover:border-brand-primary transition-colors"
                      onError={e => {
                        e.currentTarget.src = `data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><rect width='100' height='100' fill='%233B82F6'/><text x='50' y='65' font-size='50' text-anchor='middle' fill='white' font-family='sans-serif'>${incident.extra_metadata?.github?.blame?.author?.charAt(0).toUpperCase()}</text></svg>`;
                      }}
                    />
                  </a>
                  <div className="flex-1">
                    <p className="text-xs text-light-muted dark:text-dark-muted mb-0.5">Blame Author</p>
                    <a
                      href={`https://github.com/${incident.extra_metadata?.github?.blame?.author}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-sm font-semibold text-light-text dark:text-dark-text hover:text-brand-primary transition"
                    >
                      {incident.extra_metadata?.github?.blame?.author}
                    </a>
                    {incident.extra_metadata?.github?.blame?.message && (
                      <p className="text-xs text-light-muted dark:text-dark-muted mt-1 italic line-clamp-1">
                        "{incident.extra_metadata.github.blame.message}"
                      </p>
                    )}
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div className="flex items-center gap-3 p-3 bg-light-surface dark:bg-dark-surface rounded-lg border border-light-border dark:border-dark-border">
                    <GitCommit className="w-4 h-4 text-light-muted dark:text-dark-muted flex-shrink-0" />
                    <div className="flex-1 min-w-0">
                      <p className="text-xs text-light-muted dark:text-dark-muted">Commit</p>
                      <code className="text-xs text-light-text dark:text-dark-text bg-light-bg dark:bg-dark-bg px-2 py-0.5 rounded font-mono truncate block">
                        {incident.extra_metadata?.github?.blame.commit_hash?.slice(0, 8)}
                      </code>
                    </div>
                  </div>
                  <div className="flex items-center gap-3 p-3 bg-light-surface dark:bg-dark-surface rounded-lg border border-light-border dark:border-dark-border">
                    <Code className="w-4 h-4 text-light-muted dark:text-dark-muted flex-shrink-0" />
                    <div className="flex-1 min-w-0">
                      <p className="text-xs text-light-muted dark:text-dark-muted">File & Line</p>
                      <p className="text-xs text-light-text dark:text-dark-text font-mono truncate">
                        {incident.extra_metadata?.github?.blame.file}:{incident.extra_metadata?.github?.blame.line}
                      </p>
                    </div>
                  </div>
                </div>

                {incident.extra_metadata?.github?.blame.pr_number && (
                  <div className="flex items-center gap-3 pt-4 border-t border-light-border dark:border-dark-border">
                    <GitPullRequest className="w-4 h-4 text-brand-primary flex-shrink-0" />
                    <div className="flex-1">
                      <p className="text-xs text-light-muted dark:text-dark-muted mb-0.5">Associated PR</p>
                      <a
                        href={incident.extra_metadata?.github?.blame.pr_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-sm text-brand-primary hover:underline font-medium"
                      >
                        #{incident.extra_metadata?.github?.blame.pr_number}: {incident.extra_metadata?.github?.blame.pr_title}
                      </a>
                      {incident.extra_metadata?.github?.blame.pr_author && (
                        <p className="text-xs text-light-muted dark:text-dark-muted mt-0.5">
                          by {incident.extra_metadata.github.blame.pr_author}
                        </p>
                      )}
                    </div>
                  </div>
                )}

                {/* Contributors from blame */}
                {(incident.extra_metadata?.github?.blame as any)?.contributors?.length > 0 && (
                  <div className="pt-4 border-t border-light-border dark:border-dark-border">
                    <div className="flex items-center gap-2 mb-3">
                      <Users className="w-4 h-4 text-brand-secondary" />
                      <p className="text-xs font-semibold text-brand-secondary uppercase tracking-wider">Contributors</p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {((incident.extra_metadata?.github?.blame as any).contributors as Array<{
                        username: string;
                        role: string;
                        avatar?: string;
                        url?: string;
                      }>).map((c) => (
                        <a
                          key={c.username}
                          href={c.url || `https://github.com/${c.username}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="flex items-center gap-2 px-3 py-1.5 bg-light-surface dark:bg-dark-surface rounded-full border border-light-border dark:border-dark-border hover:border-brand-primary/40 transition group"
                        >
                          <img
                            src={c.avatar || `https://github.com/${c.username}.png`}
                            alt={c.username}
                            className="w-5 h-5 rounded-full"
                            onError={e => { e.currentTarget.style.display = 'none'; }}
                          />
                          <span className="text-xs font-medium text-light-text dark:text-dark-text group-hover:text-brand-primary transition">
                            {c.username}
                          </span>
                          <span className="text-xs text-light-muted dark:text-dark-muted capitalize">{c.role}</span>
                        </a>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Recent PRs from GitHub context */}
          {((incident.extra_metadata?.github?.recent_prs?.length) ?? 0) > 0 ? (
            <div className="bg-gradient-to-br from-light-card to-light-surface dark:from-dark-card dark:to-dark-surface rounded-2xl border border-light-border dark:border-dark-border shadow-xl p-6 backdrop-blur-sm">
              <div className="flex items-center gap-2 mb-4">
                <GitMerge className="w-5 h-5 text-brand-secondary" />
                <h3 className="text-sm font-semibold text-brand-secondary">Recent PRs — {incident.service_name}</h3>
                <span className="ml-auto text-xs text-light-muted dark:text-dark-muted">
                  {incident.extra_metadata!.github!.recent_prs!.length} PRs
                </span>
              </div>
              <div className="space-y-2 max-h-64 overflow-y-auto custom-scrollbar">
                {incident.extra_metadata!.github!.recent_prs!.map(pr => (
                      <div className="flex items-start gap-3 p-3 bg-light-surface dark:bg-dark-surface rounded-xl border border-light-border dark:border-dark-border hover:border-brand-primary/30 transition">
                    <GitPullRequest className="w-4 h-4 text-brand-primary mt-0.5 flex-shrink-0" />
                    <div className="flex-1 min-w-0">
                      <a
                        href={pr.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-sm font-medium text-brand-primary hover:underline line-clamp-1"
                      >
                        #{pr.number}: {pr.title}
                      </a>
                      <div className="flex items-center gap-3 mt-0.5">
                        <span className="text-xs text-light-muted dark:text-dark-muted">by {pr.author}</span>
                        {pr.merged_at && (
                          <span className="text-xs text-light-muted dark:text-dark-muted">
                            merged {new Date(pr.merged_at).toLocaleDateString()}
                          </span>
                        )}
                      </div>
                      {pr.files && pr.files.length > 0 && (
                        <div className="flex flex-wrap gap-1 mt-1.5">
                          {pr.files.slice(0, 4).map((f: string) => (
                            <span key={f} className="text-xs px-1.5 py-0.5 bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded font-mono truncate max-w-[180px]">
                              {f.split('/').pop()}
                            </span>
                          ))}
                          {pr.files.length > 4 && (
                            <span className="text-xs text-light-muted dark:text-dark-muted">+{pr.files.length - 4} more</span>
                          )}
                        </div>
                      )}
                    </div>
                    <div className="flex items-center gap-2 flex-shrink-0 text-xs">
                      {pr.additions != null && <span className="text-brand-success font-mono">+{pr.additions}</span>}
                      {pr.deletions != null && <span className="text-severity-critical font-mono">-{pr.deletions}</span>}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border p-6 text-center">
              <GitMerge className="w-8 h-8 text-light-muted dark:text-dark-muted mx-auto mb-2 opacity-50" />
              <p className="text-sm font-medium text-light-muted dark:text-dark-muted">No recent PRs found</p>
              <p className="text-xs text-light-muted dark:text-dark-muted mt-1">Related pull requests in {incident.service_name} will appear here</p>
            </div>
          )}

          {/* Auto-Fix Preview - Diff view with approve/reject */}
          {incident.extra_metadata?.auto_fix && (
            <div className="bg-gradient-to-br from-light-card to-light-surface dark:from-dark-card dark:to-dark-surface rounded-2xl border border-light-border dark:border-dark-border shadow-xl overflow-hidden backdrop-blur-sm">
              <div className="bg-light-bg dark:bg-dark-bg px-4 py-2 flex items-center justify-between border-b border-light-border dark:border-dark-border">
                <div className="flex items-center gap-2">
                  <Zap className="w-4 h-4 text-brand-warning" />
                  <span className="text-sm text-light-muted dark:text-dark-muted font-mono">Auto-Fix Preview</span>
                </div>
                <div className="flex items-center gap-2">
                  {(incident.extra_metadata.auto_fix.status === 'approved' || incident.extra_metadata.auto_fix.approved) && (
                    <span className="text-xs bg-brand-success/20 text-brand-success px-2 py-1 rounded-full border border-brand-success/30">
                      Approved
                    </span>
                  )}
                  {(incident.extra_metadata.auto_fix.status === 'rejected' || incident.extra_metadata.auto_fix.rejected) && (
                    <span className="text-xs bg-severity-critical/20 text-severity-critical px-2 py-1 rounded-full border border-severity-critical/30">
                      Rejected
                    </span>
                  )}
                  {!(incident.extra_metadata.auto_fix.status === 'approved' || incident.extra_metadata.auto_fix.approved || 
                      incident.extra_metadata.auto_fix.status === 'rejected' || incident.extra_metadata.auto_fix.rejected) && (
                    <span className="text-xs bg-brand-warning/20 text-brand-warning px-2 py-1 rounded-full border border-brand-warning/30">
                      Pending Approval
                    </span>
                  )}
                </div>
              </div>
              <div className="p-6 space-y-4">
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
                  <motion.div
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="mt-4 p-4 bg-gradient-to-r from-brand-success/10 to-brand-success/5 border border-brand-success/20 rounded-xl"
                  >
                    <p className="text-sm text-brand-success font-medium">{actionMessage}</p>
                  </motion.div>
                )}
                {isPendingAutoFix(incident.extra_metadata.auto_fix) && (
                  <div className="space-y-3 pt-4 border-t border-light-border dark:border-dark-border">
                    <Link
                      to="/approvals"
                      className="flex items-center justify-center gap-3 px-6 py-4 bg-gradient-to-r from-brand-primary to-brand-primary/90 hover:from-brand-primary/90 hover:to-brand-primary text-white rounded-xl transition-all duration-200 shadow-lg shadow-brand-primary/20 text-lg font-semibold"
                    >
                      <ExternalLink className="w-5 h-5" />
                      Review in Approvals
                    </Link>
                    <p className="text-xs text-center text-light-muted dark:text-dark-muted">
                      Go to Approvals page to review and approve/reject this fix
                    </p>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Related PRs Section */}
          {((incident.extra_metadata?.github?.related_prs?.length) ?? 0) > 0 ? (
            <div className="bg-gradient-to-br from-light-card to-light-surface dark:from-dark-card dark:to-dark-surface rounded-2xl border border-light-border dark:border-dark-border shadow-xl p-6 backdrop-blur-sm">
              <div className="flex items-center gap-2 mb-4">
                <GitPullRequest className="w-5 h-5 text-brand-primary" />
                <h3 className="text-sm font-semibold text-brand-primary">Related Pull Requests</h3>
              </div>
              <div className="space-y-3">
                {incident.extra_metadata!.github!.related_prs!.map((pr: any, index: number) => (
                  <motion.div
                    key={pr.number || index}
                    initial={{ opacity: 0, x: -20 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: index * 0.1 }}
                    className="p-4 bg-light-surface dark:bg-dark-surface rounded-xl border border-light-border dark:border-dark-border hover:shadow-md transition-shadow"
                  >
                    <div className="flex items-start justify-between mb-2">
                      <div className="flex-1">
                        <a
                          href={pr.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-sm font-medium text-brand-primary hover:underline"
                        >
                          #{pr.number}: {pr.title}
                        </a>
                        <p className="text-xs text-light-muted dark:text-dark-muted mt-1">
                          by {pr.author} • {new Date(pr.created_at).toLocaleDateString()}
                        </p>
                      </div>
                      {pr.relevance_score && (
                        <div className="ml-4">
                          <div className="flex items-center gap-2 mb-1">
                            <span className="text-xs text-light-muted dark:text-dark-muted">Relevance</span>
                            <span className="text-xs font-semibold text-brand-primary">{Math.round(pr.relevance_score)}%</span>
                          </div>
                          <div className="w-20 h-2 bg-light-bg dark:bg-dark-bg rounded-full overflow-hidden">
                            <div 
                              className="h-full bg-gradient-to-r from-brand-primary to-brand-secondary"
                              style={{ width: `${Math.round(pr.relevance_score)}%` }}
                            />
                          </div>
                        </div>
                      )}
                    </div>
                    {pr.reason && (
                      <div className="mt-2 p-2 bg-light-bg dark:bg-dark-bg rounded-lg">
                        <p className="text-xs text-light-muted dark:text-dark-muted">
                          <span className="font-medium">Why related:</span> {pr.reason}
                        </p>
                      </div>
                    )}
                  </motion.div>
                ))}
              </div>
            </div>
          ) : (
            <div className="bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border p-6 text-center">
              <GitPullRequest className="w-8 h-8 text-light-muted dark:text-dark-muted mx-auto mb-2 opacity-50" />
              <p className="text-sm font-medium text-light-muted dark:text-dark-muted">No related PRs found</p>
              <p className="text-xs text-light-muted dark:text-dark-muted mt-1">Pull requests related to this incident will appear here</p>
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