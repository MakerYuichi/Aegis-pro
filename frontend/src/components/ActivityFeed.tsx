import { useEffect, useState } from 'react';
import { Activity, Clock, CheckCircle, Eye, RotateCcw, AlertTriangle, Bell } from 'lucide-react';
import type { Incident } from '../utils/api';
import { motion, AnimatePresence } from 'framer-motion';

interface ActivityItem {
  type: string;
  action: string;
  incident_id: string;
  user: string;
  timestamp: string;
  message: string;
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
      message: `🆕 Incident ${incident.incident_id} created - ${incident.service_name} (${incident.severity})`
    }));
    setActivities(pastActivities);
    
    // Track which incident IDs we've already shown
    const ids = new Set(initialIncidents.map(i => i.incident_id));
    setUsedIncidentIds(ids);
  }, [initialIncidents]);

  // Handle real-time activities (deduplicated)
  useEffect(() => {
    if (!websocket) return;

    const handleMessage = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data);
        
        // Handle new incident broadcast
        if (data.type === 'new_incident' && data.data) {
          const incident = data.data;
          
          // Check if we already have this incident
          if (!usedIncidentIds.has(incident.incident_id)) {
            const newActivity: ActivityItem = {
              type: 'new',
              action: 'created',
              incident_id: incident.incident_id,
              user: 'System',
              timestamp: new Date().toISOString(),
              message: `🆕 New incident ${incident.incident_id} - ${incident.service_name} (${incident.severity})`
            };
            setActivities(prev => [newActivity, ...prev]);
            setUsedIncidentIds(prev => new Set(prev).add(incident.incident_id));
          }
        }
        
        // Handle user actions (rollback, acknowledge, view_details)
        if (data.type === 'activity') {
          // Check if this is a duplicate (same incident + action + user)
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
      case 'rollback': return <RotateCcw className="w-4 h-4 text-severity-critical" />;
      case 'acknowledge': return <CheckCircle className="w-4 h-4 text-brand-success" />;
      case 'view_details': return <Eye className="w-4 h-4 text-brand-primary" />;
      case 'created': return <AlertTriangle className="w-4 h-4 text-brand-warning" />;
      default: return <Activity className="w-4 h-4 text-light-muted dark:text-dark-muted" />;
    }
  };

  const getActionColor = (action: string) => {
    switch (action) {
      case 'rollback': return 'bg-severity-critical/10 border-severity-critical/30';
      case 'acknowledge': return 'bg-brand-success/10 border-brand-success/30';
      case 'view_details': return 'bg-brand-primary/10 border-brand-primary/30';
      case 'created': return 'bg-brand-warning/10 border-brand-warning/30';
      default: return 'bg-light-surface dark:bg-dark-surface border-light-border dark:border-dark-border';
    }
  };

  return (
    <div className="bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border shadow-lg p-4">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-light-text dark:text-dark-text flex items-center gap-2">
          <Activity className="w-5 h-5 text-brand-primary" />
          Live Activity Feed
        </h3>
        <div className="flex items-center gap-2">
          <Bell className="w-4 h-4 text-brand-primary animate-pulse" />
          <span className="text-xs text-light-muted dark:text-dark-muted">
            {activities.length} activities
          </span>
        </div>
      </div>

      <div className="space-y-2 max-h-64 overflow-y-auto custom-scrollbar">
        <AnimatePresence>
          {activities.length === 0 ? (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="text-center py-8"
            >
              <Activity className="w-8 h-8 text-light-muted dark:text-dark-muted mx-auto mb-2" />
              <p className="text-sm text-light-muted dark:text-dark-muted">Waiting for activity...</p>
            </motion.div>
          ) : (
            activities.map((activity, index) => (
              <motion.div
                key={`${activity.incident_id}-${activity.action}-${activity.timestamp}-${index}`}
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -20 }}
                transition={{ duration: 0.3 }}
                className={`flex items-center gap-3 p-2 rounded-lg border ${getActionColor(activity.action)}`}
              >
                <div className="flex-shrink-0">
                  {getActionIcon(activity.action)}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-light-text dark:text-dark-text truncate">
                    {activity.message}
                  </p>
                  <p className="text-xs text-light-muted dark:text-dark-muted flex items-center gap-1">
                    <Clock className="w-3 h-3" />
                    {new Date(activity.timestamp).toLocaleTimeString()}
                  </p>
                </div>
                <div className="flex-shrink-0">
                  <span className="text-xs bg-light-border dark:bg-dark-border px-2 py-0.5 rounded-full text-light-text dark:text-dark-text">
                    {activity.incident_id}
                  </span>
                </div>
              </motion.div>
            ))
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
