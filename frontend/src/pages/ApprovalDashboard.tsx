/**
 * ApprovalDashboard - Advanced Auto-Fix Approval Workflow
 *
 * Features:
 * - Shows ALL incidents with auto_fix entry
 * - Pending fixes: green banner + inline approval modal
 * - Rejected fixes: red tag at top with rejection reason
 * - Approved fixes: grey tag showing PR link
 * - GitHub context: blame author, recent PRs, contributors
 * - Code context: diff viewer with syntax highlighting
 * - Review button opens modal with full context
 */
import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import {
  CheckCircle, XCircle, RefreshCw, GitPullRequest, Filter,
  Search, Clock, Code, Eye, Zap, ChevronDown, ChevronUp, X,
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { getIncidents, approveFix, rejectFix, type Incident } from '../utils/api';

// ── helpers ────────────────────────────────────────────────────────────────

function autoFixStatus(inc: Incident): 'pending' | 'approved' | 'rejected' | 'none' {
  const af = inc.extra_metadata?.auto_fix;
  if (!af) return 'none';
  if (af.approved || (af.status && (af.status === 'approved' || af.status === 'pr_created'))) return 'approved';
  if (af.rejected || af.status === 'rejected') return 'rejected';
  if (
    af.requires_approval ||
    af.pr?.approval_required ||
    af.status === 'fix_generated' ||
    af.status === 'pr_draft'
  ) return 'pending';
  return 'none';
}

function sevColor(s: string) {
  if (s === 'P0') return 'border-severity-critical bg-severity-critical/10 text-severity-critical';
  if (s === 'P1') return 'border-severity-high bg-severity-high/10 text-severity-high';
  if (s === 'P2') return 'border-severity-medium bg-severity-medium/10 text-severity-medium';
  return 'border-light-border dark:border-dark-border bg-light-surface dark:bg-dark-surface text-light-text dark:text-dark-text';
}

// ── Inline Approval Modal ──────────────────────────────────────────────────

function ApprovalModal({
  incident,
  onClose,
  onApprove,
  onReject,
  processing,
}: {
  incident: Incident;
  onClose: () => void;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  processing: string | null;
}) {
  const af = incident.extra_metadata?.auto_fix!;
  const status = autoFixStatus(incident);
  const diff = af.pr?.fix_preview || af.diff || af.fix || '';
  const explanation = af.explanation || af.pr?.message || af.fix || '';
  const github = incident.extra_metadata?.github;
  const blame = github?.blame;
  const contributors = blame?.contributors || [];

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />

      {/* Panel */}
      <motion.div
        initial={{ scale: 0.96, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        exit={{ scale: 0.96, opacity: 0 }}
        transition={{ type: 'spring', damping: 28, stiffness: 300 }}
        className="relative w-full max-w-4xl max-h-[90vh] flex flex-col bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border shadow-2xl overflow-hidden"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-light-border dark:border-dark-border bg-gradient-to-r from-brand-primary/5 to-brand-secondary/5">
          <div className="flex items-center gap-3 min-w-0">
            <Zap className="w-5 h-5 text-brand-warning flex-shrink-0" />
            <div className="min-w-0">
              <h2 className="text-base font-semibold text-light-text dark:text-dark-text truncate">{incident.title}</h2>
              <p className="text-xs text-light-muted dark:text-dark-muted font-mono">
                {incident.incident_id} · {incident.service_name} · {incident.severity}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            {/* status badge */}
            {status === 'approved' && (
              <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-brand-success/15 text-brand-success border border-brand-success/30">
                Approved
              </span>
            )}
            {status === 'rejected' && (
              <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-severity-critical/15 text-severity-critical border border-severity-critical/30">
                Rejected
              </span>
            )}
            {status === 'pending' && (
              <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-brand-warning/15 text-brand-warning border border-brand-warning/30">
                Pending
              </span>
            )}
            <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-light-surface dark:hover:bg-dark-surface transition">
              <X className="w-4 h-4 text-light-muted dark:text-dark-muted" />
            </button>
          </div>
        </div>

        {/* Scrollable body */}
        <div className="flex-1 overflow-y-auto custom-scrollbar p-6 space-y-5">
          {/* GitHub Blame & Contributors */}
          {blame && (
            <div className="bg-light-surface dark:bg-dark-surface rounded-xl border border-light-border dark:border-dark-border p-4 space-y-3">
              <div className="flex items-center gap-2">
                <GitPullRequest className="w-4 h-4 text-brand-primary" />
                <h3 className="text-sm font-bold text-light-text dark:text-dark-text">Git Blame & Contributors</h3>
              </div>
              
              {/* Blame author */}
              <div className="space-y-2">
                <p className="text-xs text-light-muted dark:text-dark-muted uppercase tracking-wide font-semibold">Last commit</p>
                <div className="flex items-center gap-3 p-3 bg-light-bg dark:bg-dark-bg rounded-lg">
                  {blame.author_avatar && (
                    <img src={blame.author_avatar} alt={blame.author} className="w-8 h-8 rounded-full flex-shrink-0" />
                  )}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold text-light-text dark:text-dark-text">{blame.author}</p>
                    <p className="text-xs text-light-muted dark:text-dark-muted font-mono">{blame.commit_hash}</p>
                    <p className="text-xs text-light-muted dark:text-dark-muted mt-1 line-clamp-1">{blame.message}</p>
                  </div>
                </div>
              </div>

              {/* Contributors */}
              {contributors.length > 0 && (
                <div className="space-y-2">
                  <p className="text-xs text-light-muted dark:text-dark-muted uppercase tracking-wide font-semibold">Related PR Contributors</p>
                  <div className="flex flex-wrap gap-2">
                    {contributors.map((contrib) => (
                      <a
                        key={contrib.username}
                        href={contrib.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-center gap-2 px-2.5 py-1.5 bg-light-bg dark:bg-dark-bg rounded-lg hover:border-brand-primary/50 border border-light-border dark:border-dark-border transition"
                      >
                        {contrib.avatar && (
                          <img src={contrib.avatar} alt={contrib.username} className="w-5 h-5 rounded-full flex-shrink-0" />
                        )}
                        <span className="text-xs font-medium text-light-text dark:text-dark-text">{contrib.username}</span>
                        <span className="text-xs px-1 py-0.5 rounded bg-light-border dark:bg-dark-border text-light-muted dark:text-dark-muted capitalize">
                          {contrib.role}
                        </span>
                      </a>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* File context */}
          {(af.file_path || af.code_context?.file_path) && (
            <div className="flex items-center gap-2 px-3 py-2 bg-light-surface dark:bg-dark-surface rounded-lg border border-light-border dark:border-dark-border w-fit">
              <Code className="w-3.5 h-3.5 text-brand-primary" />
              <span className="text-xs font-mono text-light-text dark:text-dark-text">
                {af.file_path || af.code_context?.file_path}:{af.line_number || af.code_context?.line_number || '?'}
              </span>
            </div>
          )}

          {/* Explanation */}
          {explanation && (
            <div>
              <p className="text-xs font-semibold text-light-muted dark:text-dark-muted uppercase tracking-wider mb-2">Explanation</p>
              <p className="text-sm text-light-text dark:text-dark-text bg-light-surface dark:bg-dark-surface p-4 rounded-xl border border-light-border dark:border-dark-border leading-relaxed">
                {explanation}
              </p>
            </div>
          )}

          {/* Diff */}
          {diff && (
            <div>
              <p className="text-xs font-semibold text-light-muted dark:text-dark-muted uppercase tracking-wider mb-2">Diff</p>
              <pre className="bg-[#0d1117] text-[#e6edf3] p-4 rounded-xl text-xs font-mono overflow-x-auto leading-relaxed border border-dark-border max-h-80">
                {diff.split('\n').map((line, i) => {
                  const cls = line.startsWith('+') && !line.startsWith('+++')
                    ? 'text-green-400'
                    : line.startsWith('-') && !line.startsWith('---')
                    ? 'text-red-400'
                    : line.startsWith('@@')
                    ? 'text-blue-400'
                    : '';
                  return (
                    <span key={i} className={`block ${cls}`}>{line}</span>
                  );
                })}
              </pre>
            </div>
          )}

          {/* PR status */}
          {af.pr && (
            <div className="flex items-center gap-2 px-3 py-2.5 bg-light-surface dark:bg-dark-surface rounded-lg border border-light-border dark:border-dark-border">
              <GitPullRequest className="w-4 h-4 text-brand-primary flex-shrink-0" />
              <span className="text-sm text-light-text dark:text-dark-text">
                {af.pr.approval_required ? 'Draft PR — waiting for approval before creating' : (af.pr.message || 'PR status unknown')}
              </span>
            </div>
          )}

          {/* Rejection reason */}
          {status === 'rejected' && af.rejection_reason && (
            <div className="px-4 py-3 bg-severity-critical/8 border border-severity-critical/20 rounded-xl">
              <p className="text-xs font-semibold text-severity-critical uppercase tracking-wider mb-1">Rejection reason</p>
              <p className="text-sm text-light-text dark:text-dark-text">{af.rejection_reason}</p>
            </div>
          )}

          <div className="flex justify-end">
            <Link
              to={`/incident/${incident.incident_id}`}
              className="flex items-center gap-1.5 text-xs text-light-muted dark:text-dark-muted hover:text-brand-primary transition"
            >
              <Eye className="w-3.5 h-3.5" />
              View full incident
            </Link>
          </div>
        </div>

        {/* Footer actions — only for pending */}
        {status === 'pending' && (
          <div className="flex gap-3 px-6 py-4 border-t border-light-border dark:border-dark-border bg-light-surface/40 dark:bg-dark-surface/40">
            <button
              onClick={() => onApprove(incident.incident_id)}
              disabled={processing === incident.incident_id}
              className="flex-1 flex items-center justify-center gap-2 py-2.5 bg-brand-success hover:bg-brand-success/90 text-white rounded-xl font-semibold text-sm transition disabled:opacity-50 shadow-sm"
            >
              {processing === incident.incident_id ? (
                <RefreshCw className="w-4 h-4 animate-spin" />
              ) : (
                <CheckCircle className="w-4 h-4" />
              )}
              Approve & Create PR
            </button>
            <button
              onClick={() => onReject(incident.incident_id)}
              disabled={processing === incident.incident_id}
              className="flex items-center justify-center gap-2 px-6 py-2.5 bg-severity-critical/10 hover:bg-severity-critical/20 text-severity-critical border border-severity-critical/25 rounded-xl font-semibold text-sm transition disabled:opacity-50"
            >
              <XCircle className="w-4 h-4" />
              Reject
            </button>
          </div>
        )}
      </motion.div>
    </motion.div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────

export function ApprovalDashboard() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [loading, setLoading] = useState(true);
  const [processing, setProcessing] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filterStatus, setFilterStatus] = useState<'all' | 'pending' | 'approved' | 'rejected'>('all');
  const [filterSeverity, setFilterSeverity] = useState('all');
  const [searchTerm, setSearchTerm] = useState('');
  const [modalIncident, setModalIncident] = useState<Incident | null>(null);
  const [expandedDiff, setExpandedDiff] = useState<string | null>(null);

  const fetchAll = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await getIncidents();
      // Keep only those that have an auto_fix entry
      const withFix = (data.incidents || []).filter(
        (i: Incident) => i.extra_metadata?.auto_fix != null,
      );
      setIncidents(withFix);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load incidents');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchAll(); }, []);

  const handleApprove = async (id: string) => {
    setProcessing(id);
    try {
      await approveFix(id);
      await fetchAll();
      // If the modal is open for this incident, close it
      if (modalIncident?.incident_id === id) setModalIncident(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to approve');
    } finally {
      setProcessing(null);
    }
  };

  const handleReject = async (id: string) => {
    setProcessing(id);
    try {
      await rejectFix(id);
      await fetchAll();
      if (modalIncident?.incident_id === id) setModalIncident(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to reject');
    } finally {
      setProcessing(null);
    }
  };

  const filtered = incidents.filter(inc => {
    const st = autoFixStatus(inc);
    if (filterStatus !== 'all' && st !== filterStatus) return false;
    if (filterSeverity !== 'all' && inc.severity !== filterSeverity) return false;
    const q = searchTerm.toLowerCase();
    if (q && !inc.title?.toLowerCase().includes(q) && !inc.incident_id.toLowerCase().includes(q) && !inc.service_name.toLowerCase().includes(q)) return false;
    return true;
  });

  const pendingCount = incidents.filter(i => autoFixStatus(i) === 'pending').length;

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <RefreshCw className="w-7 h-7 text-brand-primary animate-spin mx-auto" />
          <p className="mt-3 text-sm text-light-muted dark:text-dark-muted">Loading approvals…</p>
        </div>
      </div>
    );
  }

  return (
    <>
      {/* ── Approval modal overlay ────────────────────────────── */}
      <AnimatePresence>
        {modalIncident && (
          <ApprovalModal
            incident={modalIncident}
            onClose={() => setModalIncident(null)}
            onApprove={handleApprove}
            onReject={handleReject}
            processing={processing}
          />
        )}
      </AnimatePresence>

      <div className="space-y-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-light-text dark:text-dark-text">Auto-Fix Approvals</h1>
            <p className="text-sm text-light-muted dark:text-dark-muted mt-0.5">
              {incidents.length} incident{incidents.length !== 1 ? 's' : ''} with AI-generated fix
              {pendingCount > 0 && (
                <span className="ml-2 px-2 py-0.5 bg-brand-warning/15 text-brand-warning border border-brand-warning/30 rounded-full text-xs font-semibold">
                  {pendingCount} pending
                </span>
              )}
            </p>
          </div>
          <button
            onClick={fetchAll}
            className="flex items-center gap-2 px-4 py-2 bg-brand-primary text-white text-sm font-semibold rounded-lg hover:bg-brand-primary/90 transition"
          >
            <RefreshCw className="w-4 h-4" />
            Refresh
          </button>
        </div>

        {error && (
          <div className="bg-severity-critical/10 border border-severity-critical/30 rounded-xl p-4 text-sm text-severity-critical">{error}</div>
        )}

        {/* Filters */}
        <div className="flex flex-col sm:flex-row gap-3">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-light-muted dark:text-dark-muted" />
            <input
              type="text"
              placeholder="Search incident ID, title, or service…"
              value={searchTerm}
              onChange={e => setSearchTerm(e.target.value)}
              className="w-full pl-10 pr-4 py-2 text-sm bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text focus:outline-none focus:ring-2 focus:ring-brand-primary/30"
            />
          </div>
          <div className="flex items-center gap-2">
            <Filter className="w-4 h-4 text-light-muted dark:text-dark-muted flex-shrink-0" />
            <select
              value={filterStatus}
              onChange={e => setFilterStatus(e.target.value as any)}
              className="px-3 py-2 text-sm bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text focus:outline-none"
            >
              <option value="all">All Statuses</option>
              <option value="pending">Pending</option>
              <option value="approved">Approved</option>
              <option value="rejected">Rejected</option>
            </select>
            <select
              value={filterSeverity}
              onChange={e => setFilterSeverity(e.target.value)}
              className="px-3 py-2 text-sm bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text focus:outline-none"
            >
              <option value="all">All Severity</option>
              <option value="P0">P0</option>
              <option value="P1">P1</option>
              <option value="P2">P2</option>
            </select>
          </div>
        </div>

        {filtered.length === 0 ? (
          <div className="bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border p-14 text-center">
            <CheckCircle className="w-14 h-14 text-brand-success mx-auto mb-4" />
            <h3 className="text-lg font-semibold text-light-text dark:text-dark-text mb-1">Nothing to show</h3>
            <p className="text-sm text-light-muted dark:text-dark-muted">No incidents match the current filters</p>
          </div>
        ) : (
          <div className="space-y-3">
            {filtered.map((inc, idx) => {
              const st = autoFixStatus(inc);
              const af = inc.extra_metadata!.auto_fix!;
              const diffPreview = af.pr?.fix_preview || af.diff || af.fix || '';
              const isExpanded = expandedDiff === inc.incident_id;

              return (
                <motion.div
                  key={inc.incident_id}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: idx * 0.03 }}
                  className={`bg-light-card dark:bg-dark-card rounded-2xl border shadow-sm overflow-hidden ${
                    st === 'pending' ? 'border-brand-warning/40' :
                    st === 'rejected' ? 'border-severity-critical/30' :
                    'border-light-border dark:border-dark-border'
                  }`}
                >
                  {/* Status banner */}
                  {st === 'pending' && (
                    <div className="px-5 py-2 bg-brand-warning/10 border-b border-brand-warning/20 flex items-center gap-2">
                      <Zap className="w-3.5 h-3.5 text-brand-warning" />
                      <span className="text-xs font-semibold text-brand-warning">Awaiting approval — click Review to approve or reject</span>
                    </div>
                  )}
                  {st === 'rejected' && (
                    <div className="px-5 py-2 bg-severity-critical/8 border-b border-severity-critical/20 flex items-center gap-2">
                      <XCircle className="w-3.5 h-3.5 text-severity-critical" />
                      <span className="text-xs font-semibold text-severity-critical">
                        Fix rejected{af.rejection_reason ? ` — ${af.rejection_reason}` : ''}
                      </span>
                    </div>
                  )}
                  {st === 'approved' && (
                    <div className="px-5 py-2 bg-brand-success/8 border-b border-brand-success/20 flex items-center gap-2">
                      <CheckCircle className="w-3.5 h-3.5 text-brand-success" />
                      <span className="text-xs font-semibold text-brand-success">Fix approved — PR created</span>
                    </div>
                  )}

                  {/* Card body */}
                  <div className="px-5 py-4">
                    <div className="flex items-start gap-4">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1 flex-wrap">
                          <span className={`px-2 py-0.5 rounded-full text-xs font-semibold border ${sevColor(inc.severity)}`}>
                            {inc.severity}
                          </span>
                          <span className={`px-2 py-0.5 rounded-full text-xs font-medium border ${
                            inc.status === 'active'
                              ? 'bg-severity-critical/10 text-severity-critical border-severity-critical/30'
                              : 'bg-brand-success/10 text-brand-success border-brand-success/30'
                          }`}>
                            {inc.status}
                          </span>
                          <span className="text-xs text-light-muted dark:text-dark-muted flex items-center gap-1">
                            <Clock className="w-3 h-3" />
                            {new Date(inc.declared_at).toLocaleString()}
                          </span>
                        </div>
                        <h3 className="text-sm font-semibold text-light-text dark:text-dark-text mb-0.5 line-clamp-1">{inc.title}</h3>
                        <p className="text-xs text-light-muted dark:text-dark-muted font-mono">
                          {inc.incident_id} · {inc.service_name}
                          {(af.file_path || af.code_context?.file_path) && (
                            <> · <Code className="w-3 h-3 inline mx-0.5" />{af.file_path || af.code_context?.file_path}</>
                          )}
                        </p>
                        {af.explanation && (
                          <p className="text-xs text-light-muted dark:text-dark-muted mt-1.5 line-clamp-2">{af.explanation}</p>
                        )}
                      </div>

                      {/* Action buttons */}
                      <div className="flex items-center gap-2 flex-shrink-0">
                        {diffPreview && (
                          <button
                            onClick={() => setExpandedDiff(isExpanded ? null : inc.incident_id)}
                            className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs text-light-muted dark:text-dark-muted hover:text-brand-primary bg-light-surface dark:bg-dark-surface hover:bg-brand-primary/10 border border-light-border dark:border-dark-border rounded-lg transition"
                          >
                            {isExpanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                            Diff
                          </button>
                        )}
                        <button
                          onClick={() => setModalIncident(inc)}
                          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold bg-brand-primary text-white rounded-lg hover:bg-brand-primary/90 transition"
                        >
                          <Eye className="w-3.5 h-3.5" />
                          Review
                        </button>
                        {st === 'pending' && (
                          <>
                            <button
                              onClick={() => handleApprove(inc.incident_id)}
                              disabled={processing === inc.incident_id}
                              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold bg-brand-success text-white rounded-lg hover:bg-brand-success/90 disabled:opacity-50 transition"
                            >
                              {processing === inc.incident_id ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle className="w-3.5 h-3.5" />}
                              Approve
                            </button>
                            <button
                              onClick={() => handleReject(inc.incident_id)}
                              disabled={processing === inc.incident_id}
                              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold bg-severity-critical/10 text-severity-critical border border-severity-critical/25 rounded-lg hover:bg-severity-critical/20 disabled:opacity-50 transition"
                            >
                              <XCircle className="w-3.5 h-3.5" />
                              Reject
                            </button>
                          </>
                        )}
                      </div>
                    </div>

                    {/* Inline diff expand */}
                    <AnimatePresence>
                      {isExpanded && diffPreview && (
                        <motion.div
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: 'auto', opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          className="overflow-hidden mt-4"
                        >
                          <pre className="bg-[#0d1117] text-[#e6edf3] p-4 rounded-xl text-xs font-mono overflow-x-auto leading-relaxed border border-dark-border max-h-56">
                            {diffPreview.split('\n').map((line, i) => {
                              const cls = line.startsWith('+') && !line.startsWith('+++')
                                ? 'text-green-400'
                                : line.startsWith('-') && !line.startsWith('---')
                                ? 'text-red-400'
                                : line.startsWith('@@') ? 'text-blue-400' : '';
                              return <span key={i} className={`block ${cls}`}>{line}</span>;
                            })}
                          </pre>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                </motion.div>
              );
            })}
          </div>
        )}
      </div>
    </>
  );
}
