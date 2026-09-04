import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Stats } from '../components/Stats';
import { DeclareIncidentModal } from '../components/DeclareIncidentModal';
import { ActivityFeed } from '../components/ActivityFeed';
import { OnCallSummary } from '../components/OnCallSummary';
import {
  getIncidents, getServices, seedServices, sendAlert, getOnCallRoster,
  type Incident, type Service, type OnCallMember,
} from '../utils/api';
import { 
  PlusCircle, Database, RefreshCw, Zap, BellRing, AlertTriangle, 
  ChevronRight, Clock, AlertCircle, CheckCircle, TrendingUp, 
  TrendingDown, Minus, Shield, Activity, Server, Users,
  BarChart3, Gauge, Timer, Flame, LayoutGrid, List
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

export function Dashboard() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [services, setServices] = useState<Service[]>([]);
  const [roster, setRoster] = useState<OnCallMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [seeding, setSeeding] = useState(false);
  const [alertingAll, setAlertingAll] = useState(false);
  const [alertAllMsg, setAlertAllMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [ws, setWs] = useState<WebSocket | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date>(new Date());

  // WebSocket connection
  useEffect(() => {
    let websocket: WebSocket | null = null;
    let reconnectTimeout: number;

    const connectWebSocket = () => {
      try {
        websocket = new WebSocket('ws://localhost:8000/ws/incidents');
        
        websocket.onopen = () => {
          console.log('✅ WebSocket connected');
          setWs(websocket);
        };
        
        websocket.onerror = (error) => {
          console.error('❌ WebSocket error:', error);
        };
        
        websocket.onclose = () => {
          console.log('🔌 WebSocket disconnected, reconnecting in 3s...');
          setWs(null);
          reconnectTimeout = setTimeout(connectWebSocket, 3000);
        };
        
        websocket.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            if (data.type === 'new_incident' && data.data?.incident_id) {
              fetchData();
            }
          } catch (e) {
            console.error('Error parsing WebSocket message:', e);
          }
        };
      } catch (e) {
        console.error('Failed to create WebSocket:', e);
        reconnectTimeout = setTimeout(connectWebSocket, 3000);
      }
    };

    connectWebSocket();

    return () => {
      if (websocket) {
        websocket.close();
      }
      clearTimeout(reconnectTimeout);
    };
  }, []);

  const fetchData = async () => {
    try {
      setLoading(true);
      setError(null);
      const [incidentsRes, servicesRes, rosterRes] = await Promise.all([
        getIncidents(),
        getServices(),
        getOnCallRoster(),
      ]);
      setIncidents(incidentsRes.incidents || []);
      setServices(servicesRes.services || []);
      setRoster(rosterRes.roster || []);
      setLastUpdated(new Date());
    } catch (err) {
      setError('Failed to fetch data. Make sure the backend is running.');
      console.error('Error fetching data:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleSeedServices = async () => {
    try {
      setSeeding(true);
      await seedServices();
      await fetchData();
    } catch (err) {
      console.error('Error seeding services:', err);
    } finally {
      setSeeding(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handleIncidentCreated = () => {
    fetchData();
  };

  const handleAlertEveryone = async () => {
    setAlertingAll(true);
    try {
      const result = await sendAlert({
        everyone: true,
        message: '🚨 AEGIS PRO: All-hands alert — check incident dashboard immediately.',
      });
      const count = result?.count ?? roster.filter(m => m.is_active !== false).length;
      setAlertAllMsg(`✅ ${count} engineer${count !== 1 ? 's' : ''} alerted`);
      setTimeout(() => setAlertAllMsg(null), 5000);
    } catch {
      setAlertAllMsg('❌ Failed to send alert');
      setTimeout(() => setAlertAllMsg(null), 4000);
    } finally {
      setAlertingAll(false);
    }
  };

  const hasServices = services.length > 0;
  const activeIncidents = incidents.filter(i => i.status === 'active');
  const resolvedIncidents = incidents.filter(i => i.status === 'resolved');
  const criticalIncidents = incidents.filter(i => i.severity === 'P0');
  const highIncidents = incidents.filter(i => i.severity === 'P1');
  const mediumIncidents = incidents.filter(i => i.severity === 'P2');
  
  // Calculate metrics
  const resolutionRate = incidents.length > 0 
    ? Math.round((resolvedIncidents.length / incidents.length) * 100) 
    : 0;
  const activeOnCall = roster.filter(m => m.is_active !== false).length;
  const avgConfidence = incidents.length > 0 
    ? Math.round(incidents.reduce((sum, i) => sum + (i.confidence_score || 0), 0) / incidents.length * 100)
    : 0;

  if (loading) {
    return (
      <div className="flex justify-center items-center h-screen bg-gradient-to-br from-light-bg to-light-surface dark:from-dark-bg dark:to-dark-surface">
        <div className="text-center space-y-6">
          <div className="relative w-20 h-20 mx-auto">
            <div className="absolute inset-0 animate-spin rounded-full border-4 border-transparent border-t-brand-primary border-r-brand-primary/40"></div>
            <Zap className="w-10 h-10 text-brand-primary absolute top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2" />
          </div>
          <div>
            <p className="text-lg font-semibold text-light-text dark:text-dark-text">Loading AEGIS PRO</p>
            <p className="text-sm text-light-muted dark:text-dark-muted mt-1">Synchronizing incident data...</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-light-bg via-light-surface to-light-bg dark:from-dark-bg dark:via-dark-surface dark:to-dark-bg">
      {/* Fixed Header */}
      <div className="sticky top-0 z-40 backdrop-blur-xl bg-light-card/80 dark:bg-dark-card/80 border-b border-light-border dark:border-dark-border">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-3">
              <div className="p-2.5 bg-gradient-to-br from-brand-primary to-brand-secondary rounded-xl shadow-lg shadow-brand-primary/20">
                <Zap className="w-5 h-5 text-white" />
              </div>
              <div>
                <h1 className="text-xl font-bold text-light-text dark:text-dark-text">AEGIS PRO</h1>
                <p className="text-xs text-light-muted dark:text-dark-muted flex items-center gap-1">
                  <span className={`inline-block w-2 h-2 rounded-full ${activeIncidents.length > 0 ? 'bg-severity-critical animate-pulse' : 'bg-brand-success'}`}></span>
                  {activeIncidents.length > 0 ? `${activeIncidents.length} active` : 'All systems operational'}
                </p>
              </div>
            </div>
            <div className="hidden md:flex items-center gap-4 text-xs text-light-muted dark:text-dark-muted border-l border-light-border dark:border-dark-border pl-4">
              <div className="flex items-center gap-1.5">
                <Server className="w-3.5 h-3.5" />
                <span>{services.length} services</span>
              </div>
              <div className="flex items-center gap-1.5">
                <Users className="w-3.5 h-3.5" />
                <span>{activeOnCall} on-call</span>
              </div>
              <div className="flex items-center gap-1.5">
                <Timer className="w-3.5 h-3.5" />
                <span>Updated {lastUpdated.toLocaleTimeString()}</span>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={fetchData}
              className="p-2 rounded-lg hover:bg-light-surface dark:hover:bg-dark-surface transition"
              title="Refresh"
            >
              <RefreshCw className="w-4 h-4 text-light-muted dark:text-dark-muted" />
            </button>
            <button
              onClick={() => setIsModalOpen(true)}
              disabled={!hasServices}
              className={`flex items-center gap-2 px-4 py-2 rounded-xl font-semibold text-sm transition ${
                hasServices
                  ? 'bg-gradient-to-r from-brand-primary to-brand-secondary text-white hover:shadow-lg hover:shadow-brand-primary/20'
                  : 'bg-light-border dark:bg-dark-border text-light-muted dark:text-dark-muted cursor-not-allowed'
              }`}
            >
              <PlusCircle className="w-4 h-4" />
              Declare Incident
            </button>
            {hasServices && (
              <button
                onClick={handleAlertEveryone}
                disabled={alertingAll}
                className="p-2 rounded-lg text-severity-critical hover:bg-severity-critical/10 transition disabled:opacity-50 relative"
                title="Alert everyone"
              >
                {alertingAll ? <RefreshCw className="w-4 h-4 animate-spin" /> : <BellRing className="w-4 h-4" />}
                {activeIncidents.length > 0 && (
                  <span className="absolute -top-0.5 -right-0.5 w-3 h-3 bg-severity-critical rounded-full text-[8px] text-white flex items-center justify-center font-bold">
                    {activeIncidents.length}
                  </span>
                )}
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="max-w-7xl mx-auto px-6 py-8">
        {/* Alert message */}
        <AnimatePresence>
          {alertAllMsg && (
            <motion.div
              initial={{ opacity: 0, y: -8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className={`px-5 py-3 rounded-xl text-sm font-medium border flex items-center gap-2 mb-6 ${
                alertAllMsg.startsWith('✅')
                  ? 'bg-brand-success/10 border-brand-success/30 text-brand-success'
                  : 'bg-severity-critical/10 border-severity-critical/30 text-severity-critical'
              }`}
            >
              {alertAllMsg.startsWith('✅') ? <CheckCircle className="w-4 h-4" /> : <AlertCircle className="w-4 h-4" />}
              {alertAllMsg}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Seed prompt */}
        {!hasServices && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            className="bg-gradient-to-br from-brand-warning/20 to-brand-warning/5 border border-brand-warning/30 rounded-2xl p-12 text-center space-y-4 mb-6"
          >
            <Database className="w-16 h-16 text-brand-warning mx-auto" />
            <div>
              <h2 className="text-2xl font-bold text-brand-warning mb-2">No Services</h2>
              <p className="text-light-muted dark:text-dark-muted mb-6">Start by seeding demo services</p>
            </div>
            <button
              onClick={handleSeedServices}
              disabled={seeding}
              className="inline-flex items-center gap-2 px-6 py-3 bg-brand-primary text-white rounded-xl font-semibold hover:bg-brand-primary/90 transition disabled:opacity-50"
            >
              {seeding ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Database className="w-4 h-4" />}
              {seeding ? 'Seeding…' : 'Seed Services'}
            </button>
          </motion.div>
        )}

        {error && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="bg-severity-critical/10 border border-severity-critical/30 rounded-xl p-6 text-center text-severity-critical mb-6"
          >
            <p className="font-semibold mb-4">{error}</p>
            <button onClick={fetchData} className="px-6 py-2 bg-severity-critical text-white rounded-lg hover:bg-severity-critical/90 transition">
              Retry
            </button>
          </motion.div>
        )}

        {hasServices ? (
          <div className="space-y-6">
            {/* Stats Cards */}
            <Stats incidents={incidents} />

            {/* Quick Metrics Row - 4 columns */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
              <div className="bg-light-card dark:bg-dark-card rounded-xl border border-light-border dark:border-dark-border p-4">
                <div className="flex items-center gap-3">
                  <div className="p-2.5 rounded-lg bg-brand-success/10 text-brand-success">
                    <CheckCircle className="w-4 h-4" />
                  </div>
                  <div>
                    <p className="text-xs text-light-muted dark:text-dark-muted font-medium">Resolution Rate</p>
                    <p className="text-xl font-bold text-light-text dark:text-dark-text">{resolutionRate}%</p>
                  </div>
                </div>
              </div>
              <div className="bg-light-card dark:bg-dark-card rounded-xl border border-light-border dark:border-dark-border p-4">
                <div className="flex items-center gap-3">
                  <div className="p-2.5 rounded-lg bg-brand-primary/10 text-brand-primary">
                    <Gauge className="w-4 h-4" />
                  </div>
                  <div>
                    <p className="text-xs text-light-muted dark:text-dark-muted font-medium">Avg Confidence</p>
                    <p className="text-xl font-bold text-light-text dark:text-dark-text">{avgConfidence}%</p>
                  </div>
                </div>
              </div>
              <div className="bg-light-card dark:bg-dark-card rounded-xl border border-light-border dark:border-dark-border p-4">
                <div className="flex items-center gap-3">
                  <div className="p-2.5 rounded-lg bg-severity-critical/10 text-severity-critical">
                    <Flame className="w-4 h-4" />
                  </div>
                  <div>
                    <p className="text-xs text-light-muted dark:text-dark-muted font-medium">Active P0</p>
                    <p className={`text-xl font-bold ${criticalIncidents.length > 0 ? 'text-severity-critical' : 'text-light-text dark:text-dark-text'}`}>
                      {criticalIncidents.length}
                    </p>
                  </div>
                </div>
              </div>
              <div className="bg-light-card dark:bg-dark-card rounded-xl border border-light-border dark:border-dark-border p-4">
                <div className="flex items-center gap-3">
                  <div className="p-2.5 rounded-lg bg-brand-warning/10 text-brand-warning">
                    <Users className="w-4 h-4" />
                  </div>
                  <div>
                    <p className="text-xs text-light-muted dark:text-dark-muted font-medium">On-Call</p>
                    <p className="text-xl font-bold text-light-text dark:text-dark-text">{activeOnCall}</p>
                  </div>
                </div>
              </div>
            </div>

            {/* Main Grid: Activity Feed + On-Call */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              <div className="lg:col-span-2">
                <ActivityFeed websocket={ws} initialIncidents={incidents} />
              </div>
              <div>
                <OnCallSummary roster={roster} />
              </div>
            </div>

            {/* Active Incidents List */}
            <div className="bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border overflow-hidden">
              <div className="px-6 py-4 border-b border-light-border dark:border-dark-border bg-gradient-to-r from-light-surface/50 to-transparent dark:from-dark-surface/50 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <h3 className="font-bold text-light-text dark:text-dark-text">Active Incidents</h3>
                  {activeIncidents.length > 0 && (
                    <span className="text-xs bg-severity-critical/10 text-severity-critical px-2.5 py-0.5 rounded-full font-semibold">
                      {activeIncidents.length}
                    </span>
                  )}
                </div>
                <Link to="/incidents" className="text-xs text-brand-primary hover:underline font-semibold flex items-center gap-1">
                  View all
                  <ChevronRight className="w-3 h-3" />
                </Link>
              </div>

              <div className="divide-y divide-light-border dark:divide-dark-border max-h-[400px] overflow-y-auto custom-scrollbar">
                {activeIncidents.length === 0 ? (
                  <div className="p-12 text-center text-light-muted dark:text-dark-muted">
                    <CheckCircle className="w-12 h-12 mx-auto mb-3 text-brand-success/40" />
                    <p className="text-sm font-medium">All systems operational</p>
                    <p className="text-xs mt-1">No active incidents reported</p>
                  </div>
                ) : (
                  activeIncidents.slice(0, 10).map((inc, index) => (
                    <motion.div
                      key={inc.incident_id}
                      initial={{ opacity: 0, x: -10 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: index * 0.03 }}
                    >
                      <Link
                        to={`/incident/${inc.incident_id}`}
                        className="px-6 py-4 hover:bg-light-surface dark:hover:bg-dark-surface transition flex items-center gap-4 group"
                      >
                        <div className="flex-shrink-0">
                          <div className={`w-2.5 h-2.5 rounded-full ${
                            inc.severity === 'P0' ? 'bg-severity-critical animate-pulse' :
                            inc.severity === 'P1' ? 'bg-severity-high' :
                            'bg-severity-medium'
                          }`} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-0.5 flex-wrap">
                            <span className="text-sm font-medium text-light-text dark:text-dark-text truncate group-hover:text-brand-primary transition">
                              {inc.title}
                            </span>
                            <span className={`text-xs px-2 py-0.5 rounded-full font-bold ${
                              inc.severity === 'P0' ? 'bg-severity-critical/15 text-severity-critical' :
                              inc.severity === 'P1' ? 'bg-severity-high/15 text-severity-high' :
                              'bg-severity-medium/15 text-severity-medium'
                            }`}>
                              {inc.severity}
                            </span>
                            {inc.confidence_score > 0.8 && (
                              <span className="text-xs text-brand-success font-medium flex items-center gap-0.5">
                                <CheckCircle className="w-3 h-3" />
                                high confidence
                              </span>
                            )}
                          </div>
                          <div className="flex items-center gap-3 text-xs text-light-muted dark:text-dark-muted flex-wrap">
                            <span className="font-mono">{inc.service_name}</span>
                            <span>•</span>
                            <span>{new Date(inc.declared_at).toLocaleTimeString()}</span>
                            {inc.affected_services && inc.affected_services.length > 0 && (
                              <>
                                <span>•</span>
                                <span>{inc.affected_services.length} affected</span>
                              </>
                            )}
                          </div>
                        </div>
                        <ChevronRight className="w-4 h-4 text-light-muted dark:text-dark-muted group-hover:text-brand-primary group-hover:translate-x-1 transition-all flex-shrink-0" />
                      </Link>
                    </motion.div>
                  ))
                )}
                {activeIncidents.length > 10 && (
                  <div className="px-6 py-3 text-center border-t border-light-border dark:border-dark-border">
                    <Link to="/incidents" className="text-sm text-brand-primary hover:underline font-medium">
                      +{activeIncidents.length - 10} more active incidents
                    </Link>
                  </div>
                )}
              </div>
            </div>
          </div>
        ) : null}
      </div>

      <DeclareIncidentModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onSuccess={handleIncidentCreated}
        services={services}
      />
    </div>
  );
}