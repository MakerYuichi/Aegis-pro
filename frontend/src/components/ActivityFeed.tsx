import { useEffect, useState } from 'react';
import { Activity, Clock, CheckCircle, Eye, RotateCcw, AlertTriangle, Bell, TrendingUp } from 'lucide-react';
import type { Incident } from '../utils/api';
import { motion, AnimatePresence } from 'framer-motion';

interface ActivityItem {
  type: string;
  action: string;
  incident_id: string;
  user: string;
  timestamp: string;
  message: string;
  severity?: string;
}

interface ActivityFeedProps {
  websocket: WebSocket | null;
  initialIncidents?: Incident[];
}

export function ActivityFeed({ websocket, initialIncidents = [] }: ActivityFeedProps) {
  const [activities, setActivities] = useState<ActivityItem[]>([]);
  const [usedIncidentIds, setUsedIncidentIds] = useState<Set<string>>(new Set());

  // Load past incidents as initial activities (only once)
  useEffect(() => {
    const pastActivities = initialIncidents.slice(0, 10).map((incident) => ({
      type: 'past',
      action: 'created',
      incident_id: incident.incident_id,
      user: 'System',
      timestamp: incident.declared_at,
      message: `🆕 Incident ${incident.incident_id} created - ${incident.service_name} (${incident.severity})`,
      severity: incident.severity,
    }));
    setActivities(pastActivities);
    
    const ids = new Set(initialIncidents.map(i => i.incident_id));
    setUsedIncidentIds(ids);
  }, [initialIncidents]);

  // Handle real-time activities (deduplicated)
  useEffect(() => {
    if (!websocket) return;

    const handleMessage = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data);
        
        if (data.type === 'new_incident' && data.data) {
          const incident = data.data;
          
          if (!usedIncidentIds.has(incident.incident_id)) {
            const newActivity: ActivityItem = {
              type: 'new',
              action: 'created',
              incident_id: incident.incident_id,
              user: 'System',
              timestamp: new Date().toISOString(),
              message: `🆕 New incident ${incident.incident_id} - ${incident.service_name} (${incident.severity})`,
              severity: incident.severity,
            };
            setActivities(prev => [newActivity, ...prev]);
            setUsedIncidentIds(prev => new Set(prev).add(incident.incident_id));
          }
        }
        
        if (data.type === 'activity') {
          const isDuplicate = activities.some(a => 
            a.incident_id === data.incident_id && 
            a.action === data.action && 
            a.user === data.user &&
            Math.abs(new Date(a.timestamp).getTime() - new Date(data.timestamp).getTime()) < 5000
          );
          
          if (!isDuplicate) {
            setActivities(prev => [data, ...prev]);
          }
        }
      } catch (e) {
        console.error('WebSocket parse error:', e);
      }
    };

    websocket.addEventListener('message', handleMessage);
    return () => websocket.removeEventListener('message', handleMessage);
  }, [websocket, activities, usedIncidentIds]);

  const getActionIcon = (action: string) => {
    switch (action) {
      case 'rollback': return <RotateCcw className="w-5 h-5 text-severity-critical" />;
      case 'acknowledge': return <CheckCircle className="w-5 h-5 text-brand-success" />;
      case 'view_details': return <Eye className="w-5 h-5 text-brand-primary" />;
      case 'created': return <AlertTriangle className="w-5 h-5 text-brand-warning" />;
      default: return <Activity className="w-5 h-5 text-light-muted dark:text-dark-muted" />;
    }
  };

  const getActionColor = (action: string) => {
    switch (action) {
      case 'rollback': return 'bg-severity-critical/8 border-severity-critical/30 text-severity-critical';
      case 'acknowledge': return 'bg-brand-success/8 border-brand-success/30 text-brand-success';
      case 'view_details': return 'bg-brand-primary/8 border-brand-primary/30 text-brand-primary';
      case 'created': return 'bg-brand-warning/8 border-brand-warning/30 text-brand-warning';
      default: return 'bg-light-surface dark:bg-dark-surface border-light-border dark:border-dark-border text-light-text dark:text-dark-text';
    }
  };

  const getSeverityColor = (severity?: string) => {
    switch (severity) {
      case 'P0': return 'bg-severity-critical/12 text-severity-critical';
      case 'P1': return 'bg-severity-high/12 text-severity-high';
      case 'P2': return 'bg-severity-medium/12 text-severity-medium';
      default: return 'bg-light-surface dark:bg-dark-surface text-light-muted dark:text-dark-muted';
    }
  };

  return (
    <div className="bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border shadow-lg overflow-hidden flex flex-col h-full">
      {/* Header */}
      <div className="px-6 py-5 border-b border-light-border dark:border-dark-border bg-gradient-to-r from-light-surface/50 to-transparent dark:from-dark-surface/50 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-brand-primary/15 rounded-lg">
            <Activity className="w-5 h-5 text-brand-primary" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-light-text dark:text-dark-text">Live Activity</h3>
            <p className="text-xs text-light-muted dark:text-dark-muted">Real-time incidents and actions</p>
          </div>
        </div>
        <div className="flex items-center gap-2 px-2.5 py-1.5 bg-brand-primary/10 rounded-lg">
          <div className="w-2 h-2 rounded-full bg-brand-primary animate-pulse"></div>
          <span className="text-xs font-semibold text-brand-primary">{activities.length}</span>
        </div>
      </div>

      {/* Activity List */}
      <div className="flex-1 overflow-y-auto custom-scrollbar p-4 space-y-2">
        <AnimatePresence>
          {activities.length === 0 ? (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex flex-col items-center justify-center py-12 text-center"
            >
              <div className="p-3 bg-light-surface dark:bg-dark-surface rounded-lg mb-3">
                <TrendingUp className="w-6 h-6 text-light-muted dark:text-dark-muted" />
              </div>
              <p className="text-sm font-medium text-light-muted dark:text-dark-muted">Waiting for activity</p>
              <p className="text-xs text-light-muted dark:text-dark-muted mt-1">New incidents appear here</p>
            </motion.div>
          ) : (
            activities.map((activity, index) => (
              <motion.div
                key={`${activity.incident_id}-${activity.action}-${activity.timestamp}-${index}`}
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -20 }}
                transition={{ duration: 0.3 }}
                className={`flex items-start gap-3 p-2 rounded-xl border transition-all hover:shadow-sm ${getActionColor(activity.action)}`}
              >
                <div className="flex-shrink-0 mt-0.5">
                  {getActionIcon(activity.action)}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap mb-1">
                    <p className="text-xs font-semibold text-light-text dark:text-dark-text leading-tight">
                      {activity.message}
                    </p>
                    {activity.severity && (
                      <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${getSeverityColor(activity.severity)} flex-shrink-0`}>
                        {activity.severity}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-1.5 text-xs text-light-muted dark:text-dark-muted">
                    <Clock className="w-3.5 h-3.5 flex-shrink-0" />
                    <span>{new Date(activity.timestamp).toLocaleTimeString()}</span>
                    <span className="text-light-border dark:text-dark-border">•</span>
                    <span className="font-mono">{activity.incident_id}</span>
                  </div>
                </div>
              </motion.div>
            ))
          )}
        </AnimatePresence>
      </div>

      {/* Footer with live indicator */}
      {activities.length > 0 && (
        <div className="px-4 py-3 border-t border-light-border dark:border-dark-border bg-light-surface/30 dark:bg-dark-surface/30 flex items-center justify-between text-xs">
          <div className="flex items-center gap-2 text-light-muted dark:text-dark-muted">
            <Bell className="w-3.5 h-3.5 text-brand-primary animate-pulse" />
            <span>Last update {new Date().toLocaleTimeString()}</span>
          </div>
          <span className="text-light-muted dark:text-dark-muted">{activities.length} total</span>
        </div>
      )}
    </div>
  );
}
