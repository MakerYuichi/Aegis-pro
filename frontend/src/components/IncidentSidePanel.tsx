import { useEffect, useState } from 'react';
import { X, RefreshCw, Brain, Zap, GitCommit, GitPullRequest, User, ThumbsUp, Shield, AlertTriangle } from 'lucide-react';
import { getIncident, rollbackIncident, approveFix, type Incident } from '../utils/api';
import { motion, AnimatePresence } from 'framer-motion';

interface IncidentSidePanelProps {
  incidentId: string | null;
  onClose: () => void;
}

export function IncidentSidePanel({ incidentId, onClose }: IncidentSidePanelProps) {
  const [incident, setIncident] = useState<Incident | null>(null);
  const [loading, setLoading] = useState(false);
  const [rollingBack, setRollingBack] = useState(false);
  const [approvingFix, setApprovingFix] = useState(false);

  useEffect(() => {
    if (incidentId) {
      fetchIncident(incidentId);
    }
  }, [incidentId]);

  const fetchIncident = async (id: string) => {
    try {
      setLoading(true);
      const data = await getIncident(id);
      setIncident(data);
    } catch (err) {
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

  const handleApproveFix = async () => {
    if (!incident) return;
    try {
      setApprovingFix(true);
      await approveFix(incident.incident_id);
      await fetchIncident(incident.incident_id);
    } catch (err) {
      console.error('Fix approval failed:', err);
    } finally {
      setApprovingFix(false);
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

  return (
    <AnimatePresence>
      {incidentId && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40"
          />
          
          {/* Panel */}
          <motion.div
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            transition={{ type: 'spring', damping: 25, stiffness: 200 }}
            className="fixed right-0 top-0 h-full w-full max-w-2xl bg-light-card dark:bg-dark-card border-l border-light-border dark:border-dark-border shadow-2xl z-50 overflow-hidden"
          >
            <div className="h-full flex flex-col">
              {/* Header */}
              <div className="p-6 border-b border-light-border dark:border-dark-border flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="p-2 bg-brand-primary/10 rounded-lg">
                    <Shield className="w-5 h-5 text-brand-primary" />
                  </div>
                  <div>
                    <h2 className="text-lg font-bold text-light-text dark:text-dark-text">Incident Details</h2>
                    <p className="text-sm text-light-muted dark:text-dark-muted">{incidentId}</p>
                  </div>
                </div>
                <button
                  onClick={onClose}
                  className="p-2 hover:bg-light-surface dark:hover:bg-dark-surface rounded-lg transition-colors"
                >
                  <X className="w-5 h-5 text-light-muted dark:text-dark-muted" />
                </button>
              </div>

              {/* Content */}
              <div className="flex-1 overflow-y-auto p-6 space-y-6">
                {loading ? (
                  <div className="flex items-center justify-center h-64">
                    <RefreshCw className="w-8 h-8 text-brand-primary animate-spin" />
                  </div>
                ) : incident ? (
                  <>
                    {/* Title & Status */}
                    <div className="bg-light-surface dark:bg-dark-surface rounded-xl p-4 border border-light-border dark:border-dark-border">
                      <div className="flex items-center gap-3 mb-3">
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
                      <h3 className="text-xl font-bold text-light-text dark:text-dark-text mb-2">{incident.title}</h3>
                      <p className="text-light-muted dark:text-dark-muted text-sm">{incident.description}</p>
                    </div>

                    {/* AI Analysis */}
                    <div className="bg-brand-primary/10 rounded-xl p-4 border border-brand-primary/20">
                      <div className="flex items-center gap-2 mb-4">
                        <Brain className="w-5 h-5 text-brand-primary" />
                        <h4 className="text-sm font-semibold text-brand-primary">AI Analysis</h4>
                        <span className="text-xs bg-brand-primary/20 text-brand-primary px-2 py-0.5 rounded-full ml-auto">
                          {(incident.confidence_score * 100).toFixed(0)}% confidence
                        </span>
                      </div>
                      <div className="space-y-3">
                        <div>
                          <p className="text-xs text-brand-primary uppercase tracking-wider mb-1">Root Cause</p>
                          <p className="text-light-text dark:text-dark-text text-sm bg-light-card dark:bg-dark-card p-3 rounded-lg">{incident.root_cause}</p>
                        </div>
                        <div>
                          <p className="text-xs text-brand-primary uppercase tracking-wider mb-1">Suggested Fix</p>
                          <p className="text-light-text dark:text-dark-text text-sm bg-light-card dark:bg-dark-card p-3 rounded-lg border-l-4 border-brand-success">{incident.suggested_fix}</p>
                        </div>
                      </div>
                    </div>

                    {/* Git Blame */}
                    {incident.extra_metadata?.github?.blame && (
                      <div className="bg-light-surface dark:bg-dark-surface rounded-xl p-4 border border-light-border dark:border-dark-border">
                        <div className="flex items-center gap-2 mb-4">
                          <GitCommit className="w-5 h-5 text-brand-warning" />
                          <h4 className="text-sm font-semibold text-brand-warning">Git Blame</h4>
                        </div>
                        <div className="space-y-3">
                          <div className="flex items-center gap-3">
                            <User className="w-4 h-4 text-light-muted dark:text-dark-muted" />
                            <div>
                              <p className="text-xs text-light-muted dark:text-dark-muted">Author</p>
                              <p className="text-sm text-light-text dark:text-dark-text">{incident.extra_metadata.github.blame.author}</p>
                            </div>
                          </div>
                          <div className="flex items-center gap-3">
                            <GitCommit className="w-4 h-4 text-light-muted dark:text-dark-muted" />
                            <div>
                              <p className="text-xs text-light-muted dark:text-dark-muted">Commit</p>
                              <code className="text-sm text-light-text dark:text-dark-text bg-light-border dark:bg-dark-border px-2 py-0.5 rounded">
                                {incident.extra_metadata.github.blame.commit_hash}
                              </code>
                            </div>
                          </div>
                          {incident.extra_metadata.github.blame.pr_number && (
                            <div className="flex items-center gap-3 pt-2 border-t border-light-border dark:border-dark-border">
                              <GitPullRequest className="w-4 h-4 text-brand-primary" />
                              <div>
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

                    {/* Auto-Fix */}
                    {incident.extra_metadata?.auto_fix && (
                      <div className="bg-brand-success/10 rounded-xl p-4 border border-brand-success/20">
                        <div className="flex items-center gap-2 mb-4">
                          <Zap className="w-5 h-5 text-brand-success" />
                          <h4 className="text-sm font-semibold text-brand-success">Auto-Fix Generated</h4>
                          {incident.extra_metadata.auto_fix.approved && (
                            <span className="text-xs bg-brand-success/20 text-brand-success px-2 py-0.5 rounded-full ml-auto">
                              Approved
                            </span>
                          )}
                        </div>
                        <div className="space-y-3">
                          <div>
                            <p className="text-xs text-brand-success uppercase tracking-wider mb-1">Explanation</p>
                            <p className="text-light-text dark:text-dark-text text-sm bg-light-card dark:bg-dark-card p-3 rounded-lg">{incident.extra_metadata.auto_fix.explanation}</p>
                          </div>
                          <div>
                            <p className="text-xs text-brand-success uppercase tracking-wider mb-1">Diff</p>
                            <pre className="bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text p-3 rounded-lg text-xs overflow-x-auto font-mono max-h-40">
                              {incident.extra_metadata.auto_fix.diff}
                            </pre>
                          </div>
                          {!incident.extra_metadata.auto_fix.approved && (
                            <button
                              onClick={handleApproveFix}
                              disabled={approvingFix}
                              className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-brand-success hover:bg-brand-success/90 text-white rounded-lg transition disabled:opacity-50"
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
                          )}
                        </div>
                      </div>
                    )}

                    {/* Actions */}
                    {incident.status === 'active' && (
                      <div className="bg-light-surface dark:bg-dark-surface rounded-xl p-4 border border-light-border dark:border-dark-border">
                        <h4 className="text-sm font-semibold text-light-text dark:text-dark-text mb-3">Actions</h4>
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
                      </div>
                    )}
                  </>
                ) : (
                  <div className="text-center py-12">
                    <AlertTriangle className="w-12 h-12 text-light-muted dark:text-dark-muted mx-auto mb-3" />
                    <p className="text-light-muted dark:text-dark-muted">Incident not found</p>
                  </div>
                )}
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}