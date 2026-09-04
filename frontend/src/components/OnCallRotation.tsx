import { useState } from 'react';
import { Users, Clock, RotateCcw, Shield, Bell, BellRing, CheckCircle, AlertCircle } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { type OnCallMember, sendAlert } from '../utils/api';

interface OnCallRotationProps {
  roster: OnCallMember[];
  onAlert?: (engineer: string, service: string) => void;
}

export function OnCallRotation({ roster, onAlert }: OnCallRotationProps) {
  const [alertingId, setAlertingId] = useState<string | null>(null);
  const [alertingAll, setAlertingAll] = useState(false);
  const [toastMsg, setToastMsg] = useState<{ text: string; ok: boolean } | null>(null);

  const showToast = (text: string, ok = true) => {
    setToastMsg({ text, ok });
    setTimeout(() => setToastMsg(null), 3000);
  };

  const getNextRotationTime = () => {
    const now = new Date();
    const next = new Date(now.getTime() + 4 * 60 * 60 * 1000);
    const diff = next.getTime() - now.getTime();
    const h = Math.floor(diff / (1000 * 60 * 60));
    const m = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
    return `${h}h ${m}m`;
  };

  const primary = roster.filter(m => m.role === 'primary' && m.is_active !== false);
  const secondary = roster.filter(m => m.role === 'secondary' && m.is_active !== false);
  const tertiary = roster.filter(m => m.role === 'tertiary' && m.is_active !== false);

  const handleSlackAlert = async (member: OnCallMember) => {
    const key = String(member.id);
    setAlertingId(key);
    try {
      await sendAlert({
        target: member.slack_handle,
        message: `🚨 AEGIS PRO: You are being paged for ${member.service_name || 'a service incident'}. Please acknowledge.`,
        service_name: member.service_name,
      });
      showToast(`✅ Slack alert sent to ${member.slack_handle}`);
      onAlert?.(member.slack_handle, member.service_name || '');
    } catch {
      showToast(`❌ Failed to alert ${member.slack_handle}`, false);
    } finally {
      setAlertingId(null);
    }
  };

  const handleAlertEveryone = async () => {
    setAlertingAll(true);
    try {
      await sendAlert({
        everyone: true,
        message: '🚨 AEGIS PRO: All hands alert — please check the incident dashboard immediately.',
      });
      showToast(`✅ All ${roster.filter(m => m.is_active !== false).length} engineers alerted via Slack`);
    } catch {
      showToast('❌ Failed to send broadcast alert', false);
    } finally {
      setAlertingAll(false);
    }
  };

  const roleColor = (role: string) => {
    if (role === 'primary') return 'bg-brand-success/20 text-brand-success border-2 border-brand-success/30';
    if (role === 'secondary') return 'bg-brand-warning/20 text-brand-warning border-2 border-brand-warning/30';
    return 'bg-brand-primary/20 text-brand-primary border-2 border-brand-primary/30';
  };

  const renderMember = (member: OnCallMember, index: number) => {
    const key = String(member.id);
    const isAlerting = alertingId === key;
    return (
      <div key={`${key}-${index}`} className="flex items-center gap-3 py-1">
        <div className={`w-9 h-9 rounded-full flex items-center justify-center font-bold text-sm flex-shrink-0 ${roleColor(member.role)}`}>
          {member.name.charAt(0).toUpperCase()}
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-light-text dark:text-dark-text truncate">{member.name}</p>
          <p className="text-xs text-light-muted dark:text-dark-muted truncate font-mono">
            {member.slack_handle}{member.service_name ? ` · ${member.service_name}` : ''}
          </p>
        </div>
        <button
          onClick={() => handleSlackAlert(member)}
          disabled={isAlerting || alertingAll}
          title={`Send Slack alert to ${member.slack_handle}`}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-brand-primary/15 text-brand-primary hover:bg-brand-primary/30 disabled:opacity-50 rounded-lg transition-colors text-xs font-medium border border-brand-primary/20"
        >
          {isAlerting ? (
            <RotateCcw className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <Bell className="w-3.5 h-3.5" />
          )}
          {isAlerting ? 'Sending…' : 'Alert'}
        </button>
      </div>
    );
  };

  const renderGroup = (
    members: OnCallMember[],
    label: string,
    delay: number,
    style: string,
    icon: React.ReactNode,
  ) => {
    if (members.length === 0) return null;
    return (
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay }}
        className={`rounded-xl p-4 border ${style}`}
      >
        <div className="flex items-center gap-2 mb-3">
          {icon}
          <span className="text-xs font-semibold uppercase tracking-wider">{label}</span>
          <span className="ml-auto text-xs text-light-muted dark:text-dark-muted">{members.length} engineer{members.length > 1 ? 's' : ''}</span>
        </div>
        <div className="space-y-2">
          {members.map((m, i) => renderMember(m, i))}
        </div>
      </motion.div>
    );
  };

  return (
    <div className="bg-gradient-to-br from-light-card to-light-surface dark:from-dark-card dark:to-dark-surface rounded-2xl border border-light-border dark:border-dark-border shadow-xl overflow-hidden backdrop-blur-sm">
      {/* Header */}
      <div className="p-5 border-b border-light-border/50 dark:border-dark-border/50 bg-gradient-to-r from-brand-primary/5 to-brand-secondary/5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-gradient-to-br from-brand-primary/20 to-brand-secondary/20 rounded-xl shadow-sm">
              <Users className="w-5 h-5 text-brand-primary" />
            </div>
            <div>
              <h3 className="text-base font-bold text-light-text dark:text-dark-text">On-Call Rotation</h3>
              <p className="text-xs text-light-muted dark:text-dark-muted">
                {roster.filter(m => m.is_active !== false).length} active engineers
              </p>
            </div>
          </div>
          {/* Alert Everyone button */}
          <button
            onClick={handleAlertEveryone}
            disabled={alertingAll || roster.length === 0}
            title="Send Slack alert to all on-call engineers"
            className="flex items-center gap-2 px-3 py-2 bg-severity-critical/10 hover:bg-severity-critical/20 text-severity-critical rounded-xl transition-colors text-xs font-semibold border border-severity-critical/25 disabled:opacity-50"
          >
            {alertingAll ? (
              <RotateCcw className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <BellRing className="w-3.5 h-3.5" />
            )}
            {alertingAll ? 'Alerting…' : 'Alert Everyone'}
          </button>
        </div>
      </div>

      <div className="p-5 space-y-3">
        {renderGroup(
          primary, 'Primary', 0,
          'bg-brand-success/8 border-brand-success/20',
          <Shield className="w-3.5 h-3.5 text-brand-success" />,
        )}
        {renderGroup(
          secondary, 'Secondary', 0.05,
          'bg-brand-warning/8 border-brand-warning/20',
          <Shield className="w-3.5 h-3.5 text-brand-warning" />,
        )}
        {renderGroup(
          tertiary, 'Tertiary', 0.1,
          'bg-light-surface dark:bg-dark-surface border-light-border dark:border-dark-border',
          <Shield className="w-3.5 h-3.5 text-brand-primary" />,
        )}

        {roster.length === 0 && (
          <div className="text-center py-8">
            <Users className="w-10 h-10 text-light-muted dark:text-dark-muted mx-auto mb-2" />
            <p className="text-sm text-light-muted dark:text-dark-muted">No on-call engineers configured</p>
          </div>
        )}

        {/* Next Rotation */}
        <div className="bg-light-surface dark:bg-dark-surface rounded-xl p-3 border border-light-border dark:border-dark-border">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Clock className="w-4 h-4 text-brand-primary" />
              <span className="text-sm text-light-muted dark:text-dark-muted">Next rotation in</span>
            </div>
            <div className="flex items-center gap-1.5">
              <RotateCcw className="w-3.5 h-3.5 text-brand-primary animate-spin" style={{ animationDuration: '3s' }} />
              <span className="text-sm font-semibold text-light-text dark:text-dark-text">{getNextRotationTime()}</span>
            </div>
          </div>
        </div>
      </div>

      {/* Toast */}
      <AnimatePresence>
        {toastMsg && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 10 }}
            className={`mx-5 mb-4 flex items-center gap-2 px-4 py-3 rounded-xl text-sm font-medium border ${
              toastMsg.ok
                ? 'bg-brand-success/10 text-brand-success border-brand-success/25'
                : 'bg-severity-critical/10 text-severity-critical border-severity-critical/25'
            }`}
          >
            {toastMsg.ok ? <CheckCircle className="w-4 h-4" /> : <AlertCircle className="w-4 h-4" />}
            {toastMsg.text}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
