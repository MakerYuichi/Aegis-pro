/**
 * OnCallSummary — compact dashboard widget.
 * Shows only the primary on-call per service + a single Alert button.
 * Does NOT dump the full roster.
 */
import { useState } from 'react';
import { Shield, Bell, BellRing, RotateCcw, CheckCircle, AlertCircle, ChevronRight } from 'lucide-react';
import { Link } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { type OnCallMember, sendAlert } from '../utils/api';

interface OnCallSummaryProps {
  roster: OnCallMember[];
}

export function OnCallSummary({ roster }: OnCallSummaryProps) {
  const [alertingId, setAlertingId] = useState<string | null>(null);
  const [alertingAll, setAlertingAll] = useState(false);
  const [toast, setToast] = useState<{ text: string; ok: boolean } | null>(null);

  const showToast = (text: string, ok = true) => {
    setToast({ text, ok });
    setTimeout(() => setToast(null), 3000);
  };

  // Group by service, pick first primary per service
  const primaryByService = new Map<string, OnCallMember>();
  roster
    .filter(m => m.is_active !== false)
    .forEach(m => {
      const svc = m.service_name || 'general';
      if (m.role === 'primary' && !primaryByService.has(svc)) {
        primaryByService.set(svc, m);
      }
    });

  // Fallback: if no primary for a service, pick the first active member
  roster
    .filter(m => m.is_active !== false)
    .forEach(m => {
      const svc = m.service_name || 'general';
      if (!primaryByService.has(svc)) primaryByService.set(svc, m);
    });

  const entries = Array.from(primaryByService.entries()).slice(0, 5);
  const activeCount = roster.filter(m => m.is_active !== false).length;

  const alertPerson = async (member: OnCallMember) => {
    const key = String(member.id);
    setAlertingId(key);
    try {
      await sendAlert({
        target: member.slack_handle,
        message: `🚨 AEGIS PRO: You are being paged for ${member.service_name || 'a service incident'}. Please acknowledge immediately.`,
        service_name: member.service_name,
      });
      showToast(`Alerted ${member.slack_handle} on Slack`);
    } catch {
      showToast(`Failed to alert ${member.slack_handle}`, false);
    } finally {
      setAlertingId(null);
    }
  };

  const alertAll = async () => {
    setAlertingAll(true);
    try {
      await sendAlert({
        everyone: true,
        message: '🚨 AEGIS PRO: All-hands page. Check the incident dashboard immediately.',
      });
      showToast(`All ${activeCount} engineers alerted`);
    } catch {
      showToast('Broadcast failed', false);
    } finally {
      setAlertingAll(false);
    }
  };

  return (
    <div className="bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border shadow-lg overflow-hidden">
      {/* Header */}
      <div className="px-5 py-4 border-b border-light-border dark:border-dark-border flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="p-1.5 bg-brand-primary/10 rounded-lg">
            <Shield className="w-4 h-4 text-brand-primary" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-light-text dark:text-dark-text">On-Call Now</h3>
            <p className="text-xs text-light-muted dark:text-dark-muted">{activeCount} active engineers</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={alertAll}
            disabled={alertingAll || activeCount === 0}
            className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-semibold text-severity-critical bg-severity-critical/10 hover:bg-severity-critical/20 border border-severity-critical/25 rounded-lg transition disabled:opacity-40"
          >
            {alertingAll ? <RotateCcw className="w-3 h-3 animate-spin" /> : <BellRing className="w-3 h-3" />}
            Page All
          </button>
          <Link
            to="/oncall"
            className="flex items-center gap-1 px-2.5 py-1.5 text-xs text-light-muted dark:text-dark-muted hover:text-brand-primary transition"
          >
            View all
            <ChevronRight className="w-3 h-3" />
          </Link>
        </div>
      </div>

      {/* Compact roster — one primary per service */}
      <div className="divide-y divide-light-border dark:divide-dark-border">
        {entries.length === 0 ? (
          <div className="px-5 py-8 text-center">
            <Shield className="w-8 h-8 text-light-muted dark:text-dark-muted mx-auto mb-2" />
            <p className="text-xs text-light-muted dark:text-dark-muted">No on-call engineers configured</p>
          </div>
        ) : (
          entries.map(([svc, m], i) => {
            const isAlerting = alertingId === String(m.id);
            return (
              <motion.div
                key={svc}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.04 }}
                className="flex items-center gap-3 px-5 py-3 hover:bg-light-surface dark:hover:bg-dark-surface transition"
              >
                {/* Avatar */}
                <div className="w-8 h-8 rounded-full bg-brand-success/20 border border-brand-success/30 flex items-center justify-center text-brand-success font-bold text-sm flex-shrink-0">
                  {m.name.charAt(0).toUpperCase()}
                </div>
                {/* Info */}
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-light-text dark:text-dark-text truncate">{m.name}</p>
                  <p className="text-xs text-light-muted dark:text-dark-muted truncate">
                    <span className="font-mono">{m.slack_handle}</span>
                    {svc !== 'general' && <span className="ml-1.5 text-light-muted dark:text-dark-muted">· {svc}</span>}
                  </p>
                </div>
                {/* Primary badge */}
                <span className="text-xs px-1.5 py-0.5 bg-brand-success/10 text-brand-success rounded font-medium flex-shrink-0">
                  primary
                </span>
                {/* Alert button */}
                <button
                  onClick={() => alertPerson(m)}
                  disabled={isAlerting || alertingAll}
                  title={`Slack alert → ${m.slack_handle}`}
                  className="p-1.5 text-light-muted dark:text-dark-muted hover:text-brand-primary hover:bg-brand-primary/10 rounded-lg transition disabled:opacity-40 flex-shrink-0"
                >
                  {isAlerting ? <RotateCcw className="w-3.5 h-3.5 animate-spin" /> : <Bell className="w-3.5 h-3.5" />}
                </button>
              </motion.div>
            );
          })
        )}
      </div>

      {/* Toast */}
      <AnimatePresence>
        {toast && (
          <motion.div
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className={`mx-4 mb-3 mt-1 flex items-center gap-2 px-3 py-2.5 rounded-lg text-xs font-medium border ${
              toast.ok
                ? 'bg-brand-success/10 text-brand-success border-brand-success/25'
                : 'bg-severity-critical/10 text-severity-critical border-severity-critical/25'
            }`}
          >
            {toast.ok ? <CheckCircle className="w-3.5 h-3.5" /> : <AlertCircle className="w-3.5 h-3.5" />}
            {toast.text}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
