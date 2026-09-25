/**
 * AdminDemoPage — read-only view of the demo configuration.
 *
 * Shows the sample incident served by /api/v1/demo/default, the
 * current rate-limit policy, and the try cap. Also lets the operator
 * clear the current session's demo cookie.
 *
 * Editing these values is tracked as a follow-up issue — see the
 * banner at the top of the page.
 *
 * Route: /admin/demo
 */
import { useEffect, useState } from 'react';
import {
  RefreshCw, AlertTriangle, RotateCcw, Gauge, Timer, Target,
  FileCode, ShieldAlert,
} from 'lucide-react';
import { motion } from 'framer-motion';
import { getDemoDefault, resetDemo, type Incident } from '../utils/api';

// These are the backend's hardcoded constants in src/demo/endpoints.py.
// The admin UI mirrors them so the operator can see the policy at a
// glance. If the backend values ever change, update both.
const RATE_MAX = 20;
const RATE_WINDOW_SECONDS = 3600;
const RATE_MIN_INTERVAL_SECONDS = 3;
const MAX_TRIES = 3;
const EDITABLE_DEMO_ISSUE = '#85'; // ← update with the actual issue number

export function AdminDemoPage() {
  const [incident, setIncident] = useState<Incident | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [resetting, setResetting] = useState(false);
  const [resetDone, setResetDone] = useState(false);

  const load = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await getDemoDefault();
      setIncident(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load sample');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const handleReset = async () => {
    setResetting(true);
    setResetDone(false);
    try {
      await resetDemo();
      setResetDone(true);
      setTimeout(() => setResetDone(false), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Reset failed');
    } finally {
      setResetting(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-light-text dark:text-dark-text">
          Demo Configuration
        </h1>
        <p className="text-sm text-light-muted dark:text-dark-muted mt-0.5">
          Read-only view of what prospects see on <code className="font-mono">/demo</code>.
        </p>
      </div>

      {error && (
        <div className="bg-severity-critical/10 border border-severity-critical/30 rounded-xl p-4 text-sm text-severity-critical">
          {error}
        </div>
      )}

      {/* Editable-follow-up banner */}
      <div className="bg-brand-primary/5 border border-brand-primary/20 rounded-xl p-4 flex items-start gap-3">
        <ShieldAlert className="w-4 h-4 text-brand-primary mt-0.5 flex-shrink-0" />
        <div className="text-sm">
          <p className="text-light-text dark:text-dark-text">
            Editing the sample incident and rate limits is tracked as a
            follow-up — see <span className="font-mono">{EDITABLE_DEMO_ISSUE}</span>.
          </p>
        </div>
      </div>

      {/* Rate-limit + try cap cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <ConfigCard
          icon={Gauge}
          label="Requests per hour"
          value={String(RATE_MAX)}
          detail={`per session · window ${RATE_WINDOW_SECONDS / 60} min`}
        />
        <ConfigCard
          icon={Timer}
          label="Min interval"
          value={`${RATE_MIN_INTERVAL_SECONDS}s`}
          detail="between requests"
        />
        <ConfigCard
          icon={Target}
          label="Try cap"
          value={String(MAX_TRIES)}
          detail="successful analyses per session"
        />
      </div>

      {/* Sample incident */}
      <div className="bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border p-5">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <FileCode className="w-4 h-4 text-brand-primary" />
            <h2 className="text-sm font-bold text-light-text dark:text-dark-text">
              Sample incident (served at /api/v1/demo/default)
            </h2>
          </div>
          <button
            onClick={load}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-light-muted dark:text-dark-muted hover:text-brand-primary transition"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>

        {loading ? (
          <div className="flex items-center justify-center h-32">
            <RefreshCw className="w-6 h-6 text-brand-primary animate-spin" />
          </div>
        ) : incident ? (
          <div className="space-y-4">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-severity-critical/10 text-severity-critical border border-severity-critical/30">
                {incident.severity}
              </span>
              <span className="text-sm font-semibold text-light-text dark:text-dark-text">
                {incident.title}
              </span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
              <DetailRow label="Incident ID" value={incident.incident_id} mono />
              <DetailRow label="Service" value={incident.service_name} mono />
              <DetailRow label="File" value={incident.file_path ?? '—'} mono />
              <DetailRow label="Line" value={String(incident.line_number ?? '—')} mono />
              <DetailRow
                label="Confidence"
                value={`${(incident.confidence_score * 100).toFixed(2)}%`}
              />
              <DetailRow
                label="Affected services"
                value={String(incident.affected_services.length)}
              />
            </div>

            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-light-muted dark:text-dark-muted mb-1">
                Root cause
              </p>
              <p className="text-sm text-light-text dark:text-dark-text leading-relaxed">
                {incident.root_cause}
              </p>
            </div>

            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-light-muted dark:text-dark-muted mb-1">
                Suggested fix
              </p>
              <p className="text-sm text-light-text dark:text-dark-text leading-relaxed">
                {incident.suggested_fix}
              </p>
            </div>
          </div>
        ) : (
          <p className="text-sm text-light-muted dark:text-dark-muted">
            Could not load the sample incident.
          </p>
        )}
      </div>

      {/* Reset button */}
      <div className="bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border p-5">
        <div className="flex items-start gap-3">
          <AlertTriangle className="w-4 h-4 text-brand-warning mt-0.5 flex-shrink-0" />
          <div className="flex-1">
            <h3 className="text-sm font-semibold text-light-text dark:text-dark-text mb-1">
              Reset demo session
            </h3>
            <p className="text-xs text-light-muted dark:text-dark-muted mb-3">
              Clears the <code className="font-mono">demo_session_id</code> cookie for
              the calling browser. The next demo visit starts a fresh session
              with the full try cap. Only affects this browser, not other visitors.
            </p>
            <button
              onClick={handleReset}
              disabled={resetting}
              className="inline-flex items-center gap-2 px-4 py-2 bg-brand-primary text-white text-sm font-semibold rounded-lg hover:bg-brand-primary/90 transition disabled:opacity-50"
            >
              <RotateCcw className={`w-3.5 h-3.5 ${resetting ? 'animate-spin' : ''}`} />
              {resetDone ? 'Reset complete' : 'Reset demo session'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Presentational bits ──────────────────────────────────────────────────

function ConfigCard({
  icon: Icon,
  label,
  value,
  detail,
}: {
  icon: typeof Gauge;
  label: string;
  value: string;
  detail: string;
}) {
  const tintClass =
    'text-brand-primary bg-brand-primary/10 border-brand-primary/20';
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border p-5"
    >
      <div className="flex items-center gap-3 mb-3">
        <div className={`p-2 rounded-lg border ${tintClass}`}>
          <Icon className="w-4 h-4" />
        </div>
        <span className="text-xs font-semibold uppercase tracking-wide text-light-muted dark:text-dark-muted">
          {label}
        </span>
      </div>
      <p className="text-3xl font-bold text-light-text dark:text-dark-text">
        {value}
      </p>
      <p className="text-xs text-light-muted dark:text-dark-muted mt-1">
        {detail}
      </p>
    </motion.div>
  );
}

function DetailRow({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wide text-light-muted dark:text-dark-muted mb-0.5">
        {label}
      </p>
      <p className={`text-sm text-light-text dark:text-dark-text ${mono ? 'font-mono' : ''}`}>
        {value}
      </p>
    </div>
  );
}
