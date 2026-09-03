import { useState, useEffect } from 'react';
import { CheckCircle, XCircle, RefreshCw, Eye } from 'lucide-react';
import { motion } from 'framer-motion';
import { getPendingFixes, approveFix, rejectFix, type PendingFix } from '../utils/api';
import { Link } from 'react-router-dom';

export function ApprovalDashboard() {
  const [pendingFixes, setPendingFixes] = useState<PendingFix[]>([]);
  const [loading, setLoading] = useState(true);
  const [processing, setProcessing] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchPendingFixes();
  }, []);

  const fetchPendingFixes = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await getPendingFixes();
      setPendingFixes(data.fixes || []);
    } catch (err) {
      console.error('Error fetching pending fixes:', err);
      setError(err instanceof Error ? err.message : 'Failed to load pending fixes');
    } finally {
      setLoading(false);
    }
  };

  const handleApprove = async (fixId: string) => {
    setProcessing(fixId);
    try {
      await approveFix(fixId);
      setPendingFixes(prev => prev.filter(fix => fix.id !== fixId));
    } catch (err) {
      console.error('Error approving fix:', err);
      setError(err instanceof Error ? err.message : 'Failed to approve fix');
    } finally {
      setProcessing(null);
    }
  };

  const handleReject = async (fixId: string) => {
    setProcessing(fixId);
    try {
      await rejectFix(fixId);
      setPendingFixes(prev => prev.filter(fix => fix.id !== fixId));
    } catch (err) {
      console.error('Error rejecting fix:', err);
      setError(err instanceof Error ? err.message : 'Failed to reject fix');
    } finally {
      setProcessing(null);
    }
  };

  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case 'P0': return 'border-severity-critical bg-severity-critical/10 text-severity-critical';
      case 'P1': return 'border-severity-high bg-severity-high/10 text-severity-high';
      default: return 'border-light-border dark:border-dark-border bg-light-surface dark:bg-dark-surface text-light-text dark:text-dark-text';
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="text-center">
          <RefreshCw className="w-8 h-8 text-brand-primary animate-spin mx-auto" />
          <p className="mt-4 text-light-muted dark:text-dark-muted">Loading pending fixes...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-light-text dark:text-dark-text">Pending Fix Approvals</h1>
          <p className="text-light-muted dark:text-dark-muted">Review and approve auto-generated fixes</p>
        </div>
        <button
          onClick={fetchPendingFixes}
          className="flex items-center gap-2 px-4 py-2 bg-brand-primary text-white rounded-lg hover:bg-brand-primary/90 transition"
        >
          <RefreshCw className="w-4 h-4" />
          Refresh
        </button>
      </div>

      {error && (
        <div className="bg-severity-critical/10 border border-severity-critical/30 rounded-xl p-4 text-severity-critical text-sm">
          {error}
        </div>
      )}

      {pendingFixes.length === 0 ? (
        <div className="bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border shadow-lg p-12 text-center">
          <CheckCircle className="w-16 h-16 text-brand-success mx-auto mb-4" />
          <h3 className="text-xl font-semibold text-light-text dark:text-dark-text mb-2">All Caught Up!</h3>
          <p className="text-light-muted dark:text-dark-muted">No pending fixes waiting for approval</p>
        </div>
      ) : (
        <div className="space-y-4">
          {pendingFixes.map((fix) => (
            <motion.div
              key={fix.id}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              className="bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border shadow-lg overflow-hidden"
            >
              <div className="p-6">
                <div className="flex items-start justify-between mb-4">
                  <div className="flex-1">
                    <div className="flex items-center gap-3 mb-2">
                      <span className={`px-3 py-1 rounded-full text-xs font-medium border ${getSeverityColor(fix.severity)}`}>
                        {fix.severity}
                      </span>
                      <h3 className="text-lg font-semibold text-light-text dark:text-dark-text">{fix.title}</h3>
                    </div>
                    <div className="flex items-center gap-4 text-sm text-light-muted dark:text-dark-muted">
                      <span>{fix.incident_id}</span>
                      <span>•</span>
                      <span>{fix.file_path}:{fix.line_number}</span>
                      <span>•</span>
                      <span>{fix.created_at ? new Date(fix.created_at).toLocaleString() : ''}</span>
                    </div>
                  </div>
                  <Link
                    to={`/incident/${fix.incident_id}`}
                    className="p-2 bg-light-surface dark:bg-dark-surface rounded-lg hover:bg-light-border dark:hover:bg-dark-border transition"
                  >
                    <Eye className="w-4 h-4 text-light-muted dark:text-dark-muted" />
                  </Link>
                </div>

                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">
                  <div>
                    <p className="text-xs font-medium text-light-muted dark:text-dark-muted uppercase tracking-wider mb-2">Explanation</p>
                    <p className="text-sm text-light-text dark:text-dark-text bg-light-surface dark:bg-dark-surface p-3 rounded-lg border border-light-border dark:border-dark-border">
                      {fix.explanation}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs font-medium text-light-muted dark:text-dark-muted uppercase tracking-wider mb-2">File Context</p>
                    <pre className="bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text p-3 rounded-lg text-xs overflow-x-auto font-mono border border-light-border dark:border-dark-border">
                      {fix.file_path}:{fix.line_number}
                    </pre>
                  </div>
                </div>

                <div>
                  <p className="text-xs font-medium text-light-muted dark:text-dark-muted uppercase tracking-wider mb-2">Diff Preview</p>
                  <pre className="bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text p-4 rounded-lg text-xs overflow-x-auto font-mono border border-light-border dark:border-dark-border max-h-40">
                    {fix.diff}
                  </pre>
                </div>

                <div className="flex gap-3 pt-4 border-t border-light-border dark:border-dark-border">
                  <button
                    onClick={() => handleApprove(fix.id)}
                    disabled={processing === fix.id}
                    className="flex-1 flex items-center justify-center gap-2 px-4 py-3 bg-brand-success hover:bg-brand-success/90 text-white rounded-lg transition disabled:opacity-50"
                  >
                    {processing === fix.id ? (
                      <>
                        <RefreshCw className="w-4 h-4 animate-spin" />
                        Approving...
                      </>
                    ) : (
                      <>
                        <CheckCircle className="w-4 h-4" />
                        Approve Fix
                      </>
                    )}
                  </button>
                  <button
                    onClick={() => handleReject(fix.id)}
                    disabled={processing === fix.id}
                    className="flex-1 flex items-center justify-center gap-2 px-4 py-3 bg-severity-critical hover:bg-severity-critical/90 text-white rounded-lg transition disabled:opacity-50"
                  >
                    {processing === fix.id ? (
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
              </div>
            </motion.div>
          ))}
        </div>
      )}
    </div>
  );
}
