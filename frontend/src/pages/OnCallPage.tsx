import { useState, useEffect } from 'react';
import {
  getOnCallRoster, getAlertHistory, sendAlert,
  addOnCallMember, removeOnCallMember, getServices,
  type OnCallMember, type Alert, type Service,
} from '../utils/api';
import {
  RefreshCw, Users, BellRing, Bell, RotateCcw, Plus, Trash2, X,
  CheckCircle, AlertCircle, ChevronDown, ChevronUp, MessageSquare,
  Shield, Zap, Clock, User, Mail, Phone,
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

type Role = 'primary' | 'secondary' | 'tertiary';

const ROLE_STYLES: Record<Role, string> = {
  primary: 'bg-brand-success/15 text-brand-success border-brand-success/30',
  secondary: 'bg-brand-warning/15 text-brand-warning border-brand-warning/30',
  tertiary: 'bg-brand-primary/15 text-brand-primary border-brand-primary/30',
};

const ROLE_DOT: Record<Role, string> = {
  primary: 'bg-brand-success',
  secondary: 'bg-brand-warning',
  tertiary: 'bg-brand-primary',
};

export function OnCallPage() {
  const [roster, setRoster] = useState<OnCallMember[]>([]);
  const [services, setServices] = useState<Service[]>([]);
  const [alertHistory, setAlertHistory] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<{ text: string; ok: boolean } | null>(null);

  // Add-member form
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState<Partial<OnCallMember> & { service_name?: string }>({
    role: 'secondary',
    service_name: '',
  });
  const [saving, setSaving] = useState(false);

  // Alert states
  const [alertingAll, setAlertingAll] = useState(false);
  const [alertingId, setAlertingId] = useState<string | null>(null);
  const [removingId, setRemovingId] = useState<string | null>(null);

  // Collapse/expand
  const [historyExpanded, setHistoryExpanded] = useState(false);
  const [servicesExpanded, setServicesExpanded] = useState(false);

  const showToast = (text: string, ok = true) => {
    setToast({ text, ok });
    setTimeout(() => setToast(null), 3500);
  };

  const fetchData = async () => {
    try {
      setLoading(true);
      setError(null);
      const [rosterRes, alertsRes, svcRes] = await Promise.all([
        getOnCallRoster(),
        getAlertHistory(30),
        getServices(),
      ]);
      setRoster(rosterRes.roster || []);
      setAlertHistory(alertsRes.alerts || []);
      setServices(svcRes.services || []);
    } catch {
      setError('Failed to load on-call data');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchData(); }, []);

  // ── Actions ──────────────────────────────────────────────────────────

  const handleAlertEveryone = async () => {
    setAlertingAll(true);
    try {
      const result = await sendAlert({
        everyone: true,
        message: '🚨 AEGIS PRO: All-hands page. Check the incident dashboard immediately.',
      });
      const n = result?.count ?? roster.filter(m => m.is_active !== false).length;
      showToast(`${n} engineer${n !== 1 ? 's' : ''} alerted via Slack`);
      await fetchData();
    } catch {
      showToast('Broadcast alert failed', false);
    } finally {
      setAlertingAll(false);
    }
  };

  const handleAlert = async (member: OnCallMember) => {
    const key = String(member.id);
    setAlertingId(key);
    try {
      await sendAlert({
        target: member.slack_handle,
        message: `🚨 AEGIS PRO: You are being paged for ${member.service_name || 'an incident'}. Please acknowledge.`,
        service_name: member.service_name,
      });
      showToast(`Alerted ${member.slack_handle}`);
      await fetchData();
    } catch {
      showToast(`Failed to alert ${member.slack_handle}`, false);
    } finally {
      setAlertingId(null);
    }
  };

  const handleRemove = async (member: OnCallMember) => {
    const key = String(member.id);
    setRemovingId(key);
    try {
      await removeOnCallMember(Number(member.id));
      showToast(`${member.name} removed from roster`);
      await fetchData();
    } catch {
      showToast('Failed to remove member', false);
    } finally {
      setRemovingId(null);
    }
  };

  const handleAdd = async () => {
    if (!form.name || !form.slack_handle || !form.service_name) {
      showToast('Name, Slack handle, and service are required', false);
      return;
    }
    setSaving(true);
    try {
      await addOnCallMember({
        name: form.name,
        email: form.email,
        slack_handle: form.slack_handle,
        phone: form.phone,
        role: form.role as Role,
        service_name: form.service_name,
      } as any);
      showToast(`${form.name} added to roster`);
      setForm({ role: 'secondary', service_name: '' });
      setShowAdd(false);
      await fetchData();
    } catch {
      showToast('Failed to add member', false);
    } finally {
      setSaving(false);
    }
  };

  // ── Derived ───────────────────────────────────────────────────────────

  const active = roster.filter(m => m.is_active !== false);
  const byRole = (role: Role) => active.filter(m => m.role === role);
  const byService = (service: string) => active.filter(m => m.service_name === service);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen bg-gradient-to-br from-light-bg to-light-surface dark:from-dark-bg dark:to-dark-surface">
        <div className="text-center space-y-4">
          <div className="relative w-16 h-16 mx-auto">
            <div className="absolute inset-0 animate-spin rounded-full border-4 border-transparent border-t-brand-primary border-r-brand-primary/40"></div>
            <Users className="w-8 h-8 text-brand-primary absolute top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2" />
          </div>
          <div>
            <p className="text-lg font-semibold text-light-text dark:text-dark-text">Loading On-Call Schedule</p>
            <p className="text-sm text-light-muted dark:text-dark-muted">Retrieving roster and alert history...</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* ── Page header ─────────────────────────────────────────────────── */}
      <div className="space-y-6">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
          <div className="space-y-1">
            <h1 className="text-4xl font-bold bg-gradient-to-r from-brand-primary to-brand-secondary bg-clip-text text-transparent">
              On-Call Management
            </h1>
            <p className="text-light-muted dark:text-dark-muted">Manage escalation rotations and page on-call engineers</p>
          </div>
          <div className="flex gap-2 flex-wrap">
            <button
              onClick={handleAlertEveryone}
              disabled={alertingAll || active.length === 0}
              className="flex items-center gap-2 px-4 py-2.5 bg-severity-critical text-white text-sm font-semibold rounded-xl hover:bg-severity-critical/90 disabled:opacity-50 transition shadow-lg"
            >
              {alertingAll ? <RotateCcw className="w-4 h-4 animate-spin" /> : <BellRing className="w-4 h-4" />}
              {alertingAll ? 'Alerting…' : 'Alert Everyone'}
            </button>
            <button
              onClick={() => setShowAdd(v => !v)}
              className="flex items-center gap-2 px-4 py-2.5 bg-brand-primary text-white text-sm font-semibold rounded-xl hover:bg-brand-primary/90 transition shadow-lg"
            >
              <Plus className="w-4 h-4" />
              Add Engineer
            </button>
            <button
              onClick={fetchData}
              className="flex items-center gap-2 px-3 py-2.5 bg-light-surface dark:bg-dark-surface border border-light-border dark:border-dark-border text-light-muted dark:text-dark-muted text-sm rounded-xl hover:bg-light-border dark:hover:bg-dark-border transition"
            >
              <RefreshCw className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Quick stats */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { label: 'Active', value: active.length, icon: Users, color: 'text-brand-primary', bg: 'bg-brand-primary/10' },
            { label: 'Services', value: services.length, icon: Zap, color: 'text-brand-secondary', bg: 'bg-brand-secondary/10' },
            { label: 'Alerts Sent', value: alertHistory.length, icon: Bell, color: 'text-brand-warning', bg: 'bg-brand-warning/10' },
            { label: 'L1 Available', value: byRole('primary').length, icon: Shield, color: 'text-brand-success', bg: 'bg-brand-success/10' },
          ].map(({ label, value, icon: Icon, color, bg }, i) => (
            <motion.div
              key={label}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.05 }}
              className="bg-light-card dark:bg-dark-card rounded-xl border border-light-border dark:border-dark-border p-4 flex items-center gap-3"
            >
              <div className={`p-2 rounded-lg ${bg}`}>
                <Icon className={`w-4 h-4 ${color}`} />
              </div>
              <div>
                <p className={`text-2xl font-bold ${color}`}>{value}</p>
                <p className="text-xs text-light-muted dark:text-dark-muted">{label}</p>
              </div>
            </motion.div>
          ))}
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="bg-severity-critical/10 border border-severity-critical/30 rounded-xl p-4 text-sm text-severity-critical">{error}</div>
      )}

      {/* Toast */}
      <AnimatePresence>
        {toast && (
          <motion.div
            initial={{ opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className={`fixed top-6 right-6 flex items-center gap-2 px-4 py-3 rounded-xl text-sm font-medium border z-50 ${
              toast.ok
                ? 'bg-brand-success/10 text-brand-success border-brand-success/25'
                : 'bg-severity-critical/10 text-severity-critical border-severity-critical/25'
            }`}
          >
            {toast.ok ? <CheckCircle className="w-4 h-4" /> : <AlertCircle className="w-4 h-4" />}
            {toast.text}
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Add Engineer Form ────────────────────────────────────────────── */}
      <AnimatePresence>
        {showAdd && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="overflow-hidden"
          >
            <div className="bg-gradient-to-br from-light-card to-light-surface dark:from-dark-card dark:to-dark-surface rounded-2xl border border-light-border dark:border-dark-border shadow-lg p-6">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold text-light-text dark:text-dark-text flex items-center gap-2">
                  <Plus className="w-5 h-5 text-brand-primary" />
                  Add On-Call Engineer
                </h3>
                <button
                  onClick={() => setShowAdd(false)}
                  className="p-1.5 rounded-lg hover:bg-light-border dark:hover:bg-dark-border transition"
                >
                  <X className="w-4 h-4 text-light-muted dark:text-dark-muted" />
                </button>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {[
                  { key: 'name', placeholder: 'Full name *', type: 'text' },
                  { key: 'slack_handle', placeholder: 'Slack handle (@rahul) *', type: 'text' },
                  { key: 'email', placeholder: 'Email address', type: 'email' },
                  { key: 'phone', placeholder: 'Phone (+91…)', type: 'tel' },
                ].map(({ key, placeholder, type }) => (
                  <input
                    key={key}
                    type={type}
                    placeholder={placeholder}
                    value={(form as any)[key] || ''}
                    onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))}
                    className="px-3 py-2.5 text-sm bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text focus:outline-none focus:ring-2 focus:ring-brand-primary/30"
                  />
                ))}
                <select
                  value={form.service_name || ''}
                  onChange={e => setForm(f => ({ ...f, service_name: e.target.value }))}
                  className="px-3 py-2.5 text-sm bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text focus:outline-none"
                >
                  <option value="">Select service *</option>
                  {services.map(s => (
                    <option key={s.name} value={s.name}>{s.name}</option>
                  ))}
                </select>
                <select
                  value={form.role || 'secondary'}
                  onChange={e => setForm(f => ({ ...f, role: e.target.value as Role }))}
                  className="px-3 py-2.5 text-sm bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text focus:outline-none"
                >
                  <option value="primary">L1 — Primary</option>
                  <option value="secondary">L2 — Secondary</option>
                  <option value="tertiary">L3 — Tertiary</option>
                </select>
              </div>
              <div className="flex gap-2 mt-4">
                <button
                  onClick={handleAdd}
                  disabled={saving}
                  className="flex items-center gap-2 px-4 py-2.5 bg-brand-primary text-white text-sm font-semibold rounded-lg hover:bg-brand-primary/90 disabled:opacity-50 transition"
                >
                  {saving ? <RotateCcw className="w-4 h-4 animate-spin" /> : <CheckCircle className="w-4 h-4" />}
                  {saving ? 'Saving…' : 'Add Engineer'}
                </button>
                <button
                  onClick={() => setShowAdd(false)}
                  className="px-4 py-2.5 text-sm text-light-muted dark:text-dark-muted bg-light-border dark:bg-dark-border rounded-lg hover:bg-light-border/80 dark:hover:bg-dark-border/80 transition"
                >
                  Cancel
                </button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Escalation levels ───────────────────────────────────────────── */}
      <div>
        <div className="mb-4">
          <h2 className="text-xl font-bold text-light-text dark:text-dark-text flex items-center gap-2">
            <Zap className="w-5 h-5 text-brand-primary" />
            Escalation Levels
          </h2>
          <p className="text-sm text-light-muted dark:text-dark-muted mt-1">Rotation tiers by response time</p>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {(['primary', 'secondary', 'tertiary'] as Role[]).map((role, idx) => {
            const members = byRole(role);
            const labels = ['L1 — Immediate', 'L2 — 5 min', 'L3 — 15 min'];
            const descs = ['First responders', 'Escalated if L1 unavailable', 'Management + tertiary'];
            return (
              <motion.div
                key={role}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: idx * 0.1 }}
                className="bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border shadow-sm overflow-hidden"
              >
                {/* Role header */}
                <div className={`px-5 py-4 flex items-center justify-between border-b border-light-border dark:border-dark-border bg-gradient-to-r from-light-surface/50 to-transparent dark:from-dark-surface/50`}>
                  <div className="flex items-center gap-2">
                    <div className={`w-3 h-3 rounded-full ${ROLE_DOT[role]} animate-pulse`} />
                    <div>
                      <span className="text-sm font-bold text-light-text dark:text-dark-text capitalize">{role}</span>
                      <p className="text-xs text-light-muted dark:text-dark-muted">{descs[idx]}</p>
                    </div>
                  </div>
                  <span className={`text-xs px-2.5 py-1 rounded-full border font-bold ${ROLE_STYLES[role]}`}>
                    {labels[idx]}
                  </span>
                </div>

                {/* Members */}
                <div className="divide-y divide-light-border dark:divide-dark-border">
                  {members.length === 0 ? (
                    <p className="px-5 py-6 text-sm text-center text-light-muted dark:text-dark-muted">No engineers assigned</p>
                  ) : (
                    members.map(m => {
                      const key = String(m.id);
                      const isAlerting = alertingId === key;
                      const isRemoving = removingId === key;
                      return (
                        <div key={key} className="flex items-start gap-3 px-5 py-4 group hover:bg-light-surface dark:hover:bg-dark-surface transition">
                          <div className={`w-9 h-9 rounded-lg flex items-center justify-center font-bold text-sm flex-shrink-0 ${ROLE_STYLES[role]} border`}>
                            {m.name.charAt(0).toUpperCase()}
                          </div>
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-semibold text-light-text dark:text-dark-text">{m.name}</p>
                            <div className="flex items-center gap-2 mt-1 flex-wrap">
                              <span className="text-xs font-mono text-light-muted dark:text-dark-muted bg-light-surface dark:bg-dark-surface px-2 py-0.5 rounded">
                                {m.slack_handle}
                              </span>
                              {m.service_name && (
                                <span className="text-xs text-light-muted dark:text-dark-muted">
                                  · {m.service_name}
                                </span>
                              )}
                            </div>
                            {(m.email || m.phone) && (
                              <div className="flex items-center gap-2 mt-2 text-xs text-light-muted dark:text-dark-muted flex-wrap">
                                {m.email && (
                                  <div className="flex items-center gap-1">
                                    <Mail className="w-3 h-3" />
                                    <span>{m.email}</span>
                                  </div>
                                )}
                                {m.phone && (
                                  <div className="flex items-center gap-1">
                                    <Phone className="w-3 h-3" />
                                    <span>{m.phone}</span>
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                          <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition flex-shrink-0 mt-0.5">
                            <button
                              onClick={() => handleAlert(m)}
                              disabled={isAlerting}
                              title="Page via Slack"
                              className="p-1.5 rounded-lg text-light-muted dark:text-dark-muted hover:text-brand-primary hover:bg-brand-primary/10 transition disabled:opacity-40"
                            >
                              {isAlerting ? <RotateCcw className="w-4 h-4 animate-spin" /> : <Bell className="w-4 h-4" />}
                            </button>
                            <button
                              onClick={() => handleRemove(m)}
                              disabled={isRemoving}
                              title="Remove from roster"
                              className="p-1.5 rounded-lg text-light-muted dark:text-dark-muted hover:text-severity-critical hover:bg-severity-critical/10 transition disabled:opacity-40"
                            >
                              {isRemoving ? <RotateCcw className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
                            </button>
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              </motion.div>
            );
          })}
        </div>
      </div>

      {/* ── Services with their on-call ───────────────────────────────────── */}
      {services.length > 0 && (
        <div>
          <div className="mb-4">
            <button
              onClick={() => setServicesExpanded(v => !v)}
              className="w-full flex items-center justify-between p-4 bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border hover:bg-light-surface dark:hover:bg-dark-surface transition"
            >
              <div className="flex items-center gap-3">
                <Shield className="w-5 h-5 text-brand-secondary" />
                <div className="text-left">
                  <h2 className="text-xl font-bold text-light-text dark:text-dark-text">By Service</h2>
                  <p className="text-sm text-light-muted dark:text-dark-muted">On-call engineers per service</p>
                </div>
              </div>
              {servicesExpanded ? <ChevronUp className="w-5 h-5 text-light-muted dark:text-dark-muted flex-shrink-0" /> : <ChevronDown className="w-5 h-5 text-light-muted dark:text-dark-muted flex-shrink-0" />}
            </button>
          </div>
          <AnimatePresence>
            {servicesExpanded && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                className="overflow-hidden"
              >
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mt-4">
                  {services.map(svc => {
                    const members = byService(svc.name);
                    return (
                      <div key={svc.name} className="bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border p-5">
                        <div className="flex items-start justify-between mb-4">
                          <div>
                            <h3 className="font-semibold text-light-text dark:text-dark-text">{svc.name}</h3>
                            {svc.is_critical && (
                              <span className="text-xs px-2 py-1 rounded-full bg-severity-critical/15 text-severity-critical font-semibold mt-1 inline-block">
                                Critical Service
                              </span>
                            )}
                          </div>
                          <span className={`text-sm font-bold px-2.5 py-1 rounded-lg ${
                            members.length > 0
                              ? 'bg-brand-success/15 text-brand-success'
                              : 'bg-severity-critical/15 text-severity-critical'
                          }`}>
                            {members.length}
                          </span>
                        </div>
                        <div className="space-y-2">
                          {members.length === 0 ? (
                            <p className="text-xs text-light-muted dark:text-dark-muted text-center py-3">No on-call assigned</p>
                          ) : (
                            members.map(m => (
                              <div key={String(m.id)} className="flex items-center gap-2 p-2 bg-light-surface dark:bg-dark-surface rounded-lg">
                                <div className={`w-6 h-6 rounded flex items-center justify-center text-xs font-bold flex-shrink-0 ${ROLE_STYLES[m.role as Role]} border`}>
                                  {m.name.charAt(0)}
                                </div>
                                <div className="flex-1 min-w-0">
                                  <p className="text-xs font-medium text-light-text dark:text-dark-text truncate">{m.name}</p>
                                  <p className="text-xs text-light-muted dark:text-dark-muted font-mono">{m.slack_handle}</p>
                                </div>
                                <span className="text-xs px-1.5 py-0.5 rounded bg-light-border dark:bg-dark-border text-light-text dark:text-dark-text font-semibold capitalize">
                                  {m.role}
                                </span>
                              </div>
                            ))
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}

      {/* ── Alert History ───────────────────────────────────────────────── */}
      <div className="bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border shadow-sm overflow-hidden">
        <button
          onClick={() => setHistoryExpanded(v => !v)}
          className="w-full flex items-center justify-between px-6 py-5 hover:bg-light-surface dark:hover:bg-dark-surface transition border-b border-light-border dark:border-dark-border"
        >
          <div className="flex items-center gap-3">
            <div className="p-2 bg-brand-primary/15 rounded-lg">
              <MessageSquare className="w-4 h-4 text-brand-primary" />
            </div>
            <div className="text-left">
              <span className="text-sm font-bold text-light-text dark:text-dark-text">Slack Alert History</span>
              <p className="text-xs text-light-muted dark:text-dark-muted mt-0.5">Last 30 alerts</p>
            </div>
            <span className="text-xs px-2.5 py-1 bg-light-border dark:bg-dark-border text-light-muted dark:text-dark-muted rounded-full font-bold ml-auto">
              {alertHistory.length}
            </span>
          </div>
          {historyExpanded ? <ChevronUp className="w-4 h-4 text-light-muted dark:text-dark-muted" /> : <ChevronDown className="w-4 h-4 text-light-muted dark:text-dark-muted" />}
        </button>

        <AnimatePresence>
          {historyExpanded && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="overflow-hidden"
            >
              <div className="divide-y divide-light-border dark:divide-dark-border max-h-96 overflow-y-auto custom-scrollbar">
                {alertHistory.length === 0 ? (
                  <p className="px-6 py-8 text-sm text-center text-light-muted dark:text-dark-muted">No alerts recorded yet</p>
                ) : (
                  alertHistory.map((a, i) => (
                    <div key={i} className="flex items-start gap-3 px-6 py-4 hover:bg-light-surface dark:hover:bg-dark-surface transition">
                      <div className={`w-2 h-2 rounded-full mt-2.5 flex-shrink-0 ${a.status === 'sent' ? 'bg-brand-success' : 'bg-severity-critical'}`} />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-sm font-semibold text-light-text dark:text-dark-text flex items-center gap-1">
                            <User className="w-3.5 h-3.5" />
                            {a.engineer}
                          </span>
                          <span className={`text-xs px-2 py-0.5 rounded-full font-semibold ${
                            a.status === 'sent' ? 'bg-brand-success/15 text-brand-success' : 'bg-severity-critical/15 text-severity-critical'
                          }`}>{a.status}</span>
                        </div>
                        <p className="text-xs text-light-muted dark:text-dark-muted mb-1">{a.message}</p>
                        <p className="text-xs text-light-muted dark:text-dark-muted flex items-center gap-1">
                          <Clock className="w-3 h-3" />
                          {a.service} · {a.timestamp ? new Date(a.timestamp).toLocaleString() : 'unknown'}
                        </p>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
