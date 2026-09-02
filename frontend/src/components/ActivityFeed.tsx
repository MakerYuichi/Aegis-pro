import { useEffect, useState } from 'react';
import { Activity, Clock, CheckCircle, Eye, RotateCcw, AlertTriangle } from 'lucide-react';
import type { Incident } from '../utils/api';

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
      case 'rollback': return <RotateCcw className="w-4 h-4 text-red-500" />;
      case 'acknowledge': return <CheckCircle className="w-4 h-4 text-green-500" />;
      case 'view_details': return <Eye className="w-4 h-4 text-blue-500" />;
      case 'created': return <AlertTriangle className="w-4 h-4 text-yellow-500" />;
      default: return <Activity className="w-4 h-4 text-gray-500" />;
    }
  };

  const getActionColor = (action: string) => {
    switch (action) {
      case 'rollback': return 'bg-red-50 border-red-200 dark:bg-red-950/20 dark:border-red-900';
      case 'acknowledge': return 'bg-green-50 border-green-200 dark:bg-green-950/20 dark:border-green-900';
      case 'view_details': return 'bg-blue-50 border-blue-200 dark:bg-blue-950/20 dark:border-blue-900';
      case 'created': return 'bg-yellow-50 border-yellow-200 dark:bg-yellow-950/20 dark:border-yellow-900';
      default: return 'bg-gray-50 border-gray-200 dark:bg-gray-900/20 dark:border-gray-700';
    }
  };

  return (
    <div className="bg-white dark:bg-dark-surface rounded-xl shadow-lg p-4">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold dark:text-dark-text flex items-center gap-2">
          <Activity className="w-5 h-5 text-primary-500" />
          Live Activity Feed
        </h3>
        <span className="text-xs text-gray-500 dark:text-dark-muted">
          {activities.length} activities
        </span>
      </div>

      <div className="space-y-2 max-h-64 overflow-y-auto">
        {activities.length === 0 ? (
          <div className="text-center py-8">
            <Activity className="w-8 h-8 text-gray-300 dark:text-gray-600 mx-auto mb-2" />
            <p className="text-sm text-gray-400 dark:text-dark-muted">Waiting for activity...</p>
          </div>
        ) : (
          activities.map((activity, index) => (
            <div
              key={`${activity.incident_id}-${activity.action}-${activity.timestamp}-${index}`}
              className={`flex items-center gap-3 p-2 rounded-lg border ${getActionColor(activity.action)}`}
            >
              <div className="flex-shrink-0">
                {getActionIcon(activity.action)}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium dark:text-dark-text truncate">
                  {activity.message}
                </p>
                <p className="text-xs text-gray-500 dark:text-dark-muted flex items-center gap-1">
                  <Clock className="w-3 h-3" />
                  {new Date(activity.timestamp).toLocaleTimeString()}
                </p>
              </div>
              <div className="flex-shrink-0">
                <span className="text-xs bg-gray-100 dark:bg-dark-border px-2 py-0.5 rounded-full text-gray-600 dark:text-dark-muted">
                  {activity.incident_id}
                </span>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
