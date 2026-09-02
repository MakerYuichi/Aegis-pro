import { useEffect, useState } from 'react';
import { Activity, User, Clock, CheckCircle, Eye, RotateCcw } from 'lucide-react';

interface Activity {
  type: string;
  action: string;
  incident_id: string;
  user: string;
  timestamp: string;
  message: string;
}

export function ActivityFeed({ websocket }: { websocket: WebSocket | null }) {
  const [activities, setActivities] = useState<Activity[]>([]);

  useEffect(() => {
    if (!websocket) return;

    websocket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'activity') {
          setActivities(prev => [data, ...prev].slice(0, 50));
        }
      } catch (e) {
        console.error('WebSocket parse error:', e);
      }
    };

  }, [websocket]);

  const getActionIcon = (action: string) => {
    switch (action) {
      case 'rollback': return <RotateCcw className="w-4 h-4 text-red-500" />;
      case 'acknowledge': return <CheckCircle className="w-4 h-4 text-green-500" />;
      case 'view_details': return <Eye className="w-4 h-4 text-blue-500" />;
      default: return <Activity className="w-4 h-4 text-gray-500" />;
    }
  };

  const getActionColor = (action: string) => {
    switch (action) {
      case 'rollback': return 'bg-red-50 border-red-200';
      case 'acknowledge': return 'bg-green-50 border-green-200';
      case 'view_details': return 'bg-blue-50 border-blue-200';
      default: return 'bg-gray-50 border-gray-200';
    }
  };

  return (
    <div className="bg-white dark:bg-dark-surface rounded-xl shadow-lg p-4">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold dark:text-dark-text">Live Activity Feed</h3>
        <span className="text-xs text-gray-500 dark:text-dark-muted">
          {activities.length} activities
        </span>
      </div>

      <div className="space-y-2 max-h-64 overflow-y-auto">
        {activities.length === 0 ? (
          <div className="text-center py-8">
            <Activity className="w-8 h-8 text-gray-300 mx-auto mb-2" />
            <p className="text-sm text-gray-400">Waiting for activity...</p>
          </div>
        ) : (
          activities.map((activity, index) => (
            <div
              key={index}
              className={`flex items-center gap-3 p-2 rounded-lg border ${getActionColor(activity.action)}`}
            >
              <div className="flex-shrink-0">
                {getActionIcon(activity.action)}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium dark:text-dark-text truncate">
                  {activity.message}
                </p>
                <p className="text-xs text-gray-500 dark:text-dark-muted">
                  <Clock className="w-3 h-3 inline mr-1" />
                  {new Date(activity.timestamp).toLocaleTimeString()}
                </p>
              </div>
              <div className="flex-shrink-0">
                <span className="text-xs bg-gray-100 dark:bg-dark-border px-2 py-0.5 rounded-full">
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
