import { useState, useEffect } from 'react';
import { Users, Server, Plus, Trash2, Save, Search, Edit, X, Database, AlertCircle, Clock } from 'lucide-react';
import { getServices, getOnCallRoster, addOnCallMember, removeOnCallMember, createService, deleteService, type OnCallMember } from '../utils/api';
import { motion } from 'framer-motion';

interface TeamMemberSettings {
  id: string;
  name: string;
  email: string;
  role: string;
  slack_handle: string;
  service_name?: string;
}

interface ServiceSettings {
  id: string;
  name: string;
  description: string;
  repo_name: string;
  dependencies: string[];
  is_critical: boolean;
}

interface EscalationPolicy {
  id: string;
  name: string;
  description: string;
  levels: Array<{
    tier: number;
    delay_minutes: number;
    members: string[];
  }>;
}

export function Settings() {
  const [teamMembers, setTeamMembers] = useState<TeamMemberSettings[]>([]);
  const [services, setServices] = useState<ServiceSettings[]>([]);
  const [escalationPolicies, setEscalationPolicies] = useState<EscalationPolicy[]>([
    {
      id: '1',
      name: 'P1 Critical',
      description: 'For critical production incidents',
      levels: [
        { tier: 1, delay_minutes: 0, members: ['Primary On-Call'] },
        { tier: 2, delay_minutes: 15, members: ['Secondary On-Call'] },
        { tier: 3, delay_minutes: 30, members: ['Manager', 'Lead'] }
      ]
    },
    {
      id: '2',
      name: 'P2 High',
      description: 'For high priority incidents',
      levels: [
        { tier: 1, delay_minutes: 0, members: ['Secondary On-Call'] },
        { tier: 2, delay_minutes: 20, members: ['Manager'] }
      ]
    }
  ]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  const [newMember, setNewMember] = useState<Partial<TeamMemberSettings>>({ role: 'secondary' });
  const [newService, setNewService] = useState<Partial<ServiceSettings>>({ is_critical: false, dependencies: [] });
  const [newPolicy, setNewPolicy] = useState<Partial<EscalationPolicy>>({ name: '', description: '', levels: [] });
  const [showAddMember, setShowAddMember] = useState(false);
  const [showAddService, setShowAddService] = useState(false);
  const [showAddPolicy, setShowAddPolicy] = useState(false);
  const [editingMember, setEditingMember] = useState<string | null>(null);
  const [editingPolicy, setEditingPolicy] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [roleFilter, setRoleFilter] = useState<'all' | 'primary' | 'secondary' | 'tertiary'>('all');
  const [activeTab, setActiveTab] = useState<'team' | 'services' | 'escalation'>('team');

  useEffect(() => {
    fetchData();
  }, []);

  const fetchData = async () => {
    try {
      setLoading(true);
      setError(null);
      const [servicesRes, onCallRes] = await Promise.all([
        getServices(),
        getOnCallRoster()
      ]);
      
      setServices(servicesRes.services?.map((s: any) => ({
        id: s.id || s.name,
        name: s.name,
        description: s.description || '',
        repo_name: s.repo_name || '',
        dependencies: s.dependencies || [],
        is_critical: s.is_critical || false
      })) || []);
      
      setTeamMembers(onCallRes.roster?.map((member: OnCallMember) => ({
        id: String(member.id),
        name: member.name,
        email: member.email || '',
        role: member.role,
        slack_handle: member.slack_handle
      })) || []);
    } catch (err) {
      setError('Failed to fetch settings data');
      console.error('Error fetching settings:', err);
    } finally {
      setLoading(false);
    }
  };

  const addTeamMember = async () => {
    if (newMember.name && newMember.slack_handle) {
      try {
        await addOnCallMember({
          name: newMember.name,
          email: newMember.email,
          slack_handle: newMember.slack_handle,
          role: newMember.role || 'secondary',
          service_name: (newMember as any).service_name || services[0]?.name || 'general',
        });
        await fetchData();
        setNewMember({ role: 'secondary' });
        setShowAddMember(false);
      } catch (err) {
        console.error('Error adding team member:', err);
        setError('Failed to add team member');
      }
    }
  };

  const updateTeamMember = async (id: string) => {
    try {
      const member = teamMembers.find(m => m.id === id);
      if (member) {
        await removeOnCallMember(parseInt(id));
        await addOnCallMember({
          name: newMember.name || member.name,
          email: newMember.email || member.email,
          slack_handle: newMember.slack_handle || member.slack_handle,
          role: newMember.role || member.role,
          service_name: 'general'
        });
        await fetchData();
        setEditingMember(null);
        setNewMember({ role: 'secondary' });
      }
    } catch (err) {
      console.error('Error updating team member:', err);
      setError('Failed to update team member');
    }
  };

  const removeTeamMember = async (id: string) => {
    try {
      await removeOnCallMember(parseInt(id));
      await fetchData();
    } catch (err) {
      console.error('Error removing team member:', err);
      setError('Failed to remove team member');
    }
  };

  const addService = async () => {
    if (newService.name && newService.repo_name) {
      try {
        await createService({
          name: newService.name,
          description: newService.description || '',
          repo_name: newService.repo_name,
          dependencies: newService.dependencies || [],
          is_critical: newService.is_critical || false,
        });
        await fetchData();
        setNewService({ is_critical: false, dependencies: [] });
        setShowAddService(false);
      } catch (err) {
        console.error('Error adding service:', err);
        setError('Failed to add service');
      }
    }
  };

  const removeService = async (id: string) => {
    const service = services.find(s => s.id === id);
    if (!service) return;
    try {
      await deleteService(service.name);
      await fetchData();
    } catch (err) {
      console.error('Error removing service:', err);
      setError('Failed to remove service');
    }
  };

  const addEscalationPolicy = () => {
    if (newPolicy.name && newPolicy.description) {
      const policy: EscalationPolicy = {
        id: String(Date.now()),
        name: newPolicy.name,
        description: newPolicy.description,
        levels: newPolicy.levels || []
      };
      setEscalationPolicies([...escalationPolicies, policy]);
      setNewPolicy({ name: '', description: '', levels: [] });
      setShowAddPolicy(false);
    }
  };

  const updateEscalationPolicy = (id: string) => {
    setEscalationPolicies(escalationPolicies.map(p => 
      p.id === id 
        ? { ...newPolicy, id } as EscalationPolicy
        : p
    ));
    setEditingPolicy(null);
    setNewPolicy({ name: '', description: '', levels: [] });
  };

  const deleteEscalationPolicy = (id: string) => {
    setEscalationPolicies(escalationPolicies.filter(p => p.id !== id));
  };

  const addPolicyLevel = (policyId?: string) => {
    if (policyId) {
      // Edit mode
      const policy = escalationPolicies.find(p => p.id === policyId);
      if (policy) {
        const maxTier = Math.max(...policy.levels.map(l => l.tier), 0);
        const updatedPolicy = {
          ...policy,
          levels: [...policy.levels, { tier: maxTier + 1, delay_minutes: 0, members: [] }]
        };
        setEscalationPolicies(escalationPolicies.map(p => p.id === policyId ? updatedPolicy : p));
      }
    } else {
      // Add mode
      const levels = newPolicy.levels || [];
      const maxTier = Math.max(...levels.map(l => l.tier), 0);
      setNewPolicy({
        ...newPolicy,
        levels: [...levels, { tier: maxTier + 1, delay_minutes: 0, members: [] }]
      });
    }
  };

  const filteredMembers = teamMembers.filter(member => {
    const matchesSearch = 
      member.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      member.email.toLowerCase().includes(searchTerm.toLowerCase()) ||
      member.slack_handle.toLowerCase().includes(searchTerm.toLowerCase());
    const matchesRole = roleFilter === 'all' || member.role === roleFilter;
    return matchesSearch && matchesRole;
  });

  const filteredServices = services.filter(service =>
    service.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
    service.description.toLowerCase().includes(searchTerm.toLowerCase()) ||
    service.repo_name.toLowerCase().includes(searchTerm.toLowerCase())
  );

  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="text-center">
          <Database className="w-8 h-8 text-brand-primary animate-spin mx-auto" />
          <p className="mt-4 text-light-muted dark:text-dark-muted">Loading settings...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-light-text dark:text-dark-text">Settings</h1>
        <p className="text-light-muted dark:text-dark-muted">Manage team members, services, and escalation policies</p>
      </div>

      {error && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className="bg-severity-critical/10 border border-severity-critical/30 rounded-xl p-4 flex items-center gap-3"
        >
          <AlertCircle className="w-5 h-5 text-severity-critical flex-shrink-0" />
          <p className="text-severity-critical">{error}</p>
        </motion.div>
      )}

      {/* Tab Navigation */}
      <div className="flex gap-4 border-b border-light-border dark:border-dark-border overflow-x-auto">
        {(['team', 'services', 'escalation'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-3 font-medium text-sm transition-colors whitespace-nowrap border-b-2 ${
              activeTab === tab
                ? 'border-brand-primary text-brand-primary'
                : 'border-transparent text-light-muted dark:text-dark-muted hover:text-light-text dark:hover:text-dark-text'
            }`}
          >
            {tab === 'team' && <span className="flex items-center gap-2"><Users className="w-4 h-4" /> Team</span>}
            {tab === 'services' && <span className="flex items-center gap-2"><Server className="w-4 h-4" /> Services</span>}
            {tab === 'escalation' && <span className="flex items-center gap-2"><AlertCircle className="w-4 h-4" /> Escalation</span>}
          </button>
        ))}
      </div>

      {/* Search Bar */}
      <div className="bg-gradient-to-br from-light-card to-light-surface dark:from-dark-card dark:to-dark-surface rounded-2xl border border-light-border dark:border-dark-border shadow-xl p-4 backdrop-blur-sm">
        <div className="flex flex-col md:flex-row gap-4">
          <div className="flex-1 relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-light-muted dark:text-dark-muted" />
            <input
              type="text"
              placeholder={activeTab === 'team' ? 'Search members...' : activeTab === 'services' ? 'Search services...' : 'Search policies...'}
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full pl-10 pr-4 py-2 bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text placeholder-light-muted dark:placeholder-dark-muted"
            />
          </div>
          {activeTab === 'team' && (
            <select
              value={roleFilter}
              onChange={(e) => setRoleFilter(e.target.value as any)}
              className="px-4 py-2 bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text"
            >
              <option value="all">All Roles</option>
              <option value="primary">Primary</option>
              <option value="secondary">Secondary</option>
              <option value="tertiary">Tertiary</option>
            </select>
          )}
        </div>
      </div>

      {/* Team Members Tab */}
      {activeTab === 'team' && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="bg-gradient-to-br from-light-card to-light-surface dark:from-dark-card dark:to-dark-surface rounded-2xl border border-light-border dark:border-dark-border shadow-xl p-6 backdrop-blur-sm"
        >
          <div className="flex items-center justify-between mb-6">
            <div>
              <h2 className="text-xl font-semibold text-light-text dark:text-dark-text">Team Members</h2>
              <p className="text-sm text-light-muted dark:text-dark-muted">{filteredMembers.length} members</p>
            </div>
            <button
              onClick={() => setShowAddMember(true)}
              className="flex items-center gap-2 px-4 py-2 bg-brand-primary text-white rounded-lg hover:bg-brand-primary/90 transition shadow-md"
            >
              <Plus className="w-4 h-4" />
              Add Member
            </button>
          </div>

          {showAddMember && (
            <motion.div
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              className="mb-6 p-6 bg-light-surface dark:bg-dark-surface rounded-xl border border-light-border dark:border-dark-border shadow-sm"
            >
              <h3 className="text-lg font-semibold text-light-text dark:text-dark-text mb-4">Add New Team Member</h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <input
                  type="text"
                  placeholder="Full Name"
                  value={newMember.name || ''}
                  onChange={(e) => setNewMember({ ...newMember, name: e.target.value })}
                  className="px-4 py-2 bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text placeholder-light-muted dark:placeholder-dark-muted"
                />
                <input
                  type="email"
                  placeholder="Email Address"
                  value={newMember.email || ''}
                  onChange={(e) => setNewMember({ ...newMember, email: e.target.value })}
                  className="px-4 py-2 bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text placeholder-light-muted dark:placeholder-dark-muted"
                />
                <input
                  type="text"
                  placeholder="Slack Handle"
                  value={newMember.slack_handle || ''}
                  onChange={(e) => setNewMember({ ...newMember, slack_handle: e.target.value })}
                  className="px-4 py-2 bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text placeholder-light-muted dark:placeholder-dark-muted"
                />
                <select
                  value={newMember.role || 'secondary'}
                  onChange={(e) => setNewMember({ ...newMember, role: e.target.value })}
                  className="px-4 py-2 bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text"
                >
                  <option value="primary">Primary</option>
                  <option value="secondary">Secondary</option>
                  <option value="tertiary">Tertiary</option>
                </select>
              </div>
              <div className="flex gap-2 mt-4">
                <button
                  onClick={addTeamMember}
                  className="flex items-center gap-2 px-4 py-2 bg-brand-success text-white rounded-lg hover:bg-brand-success/90 transition shadow-md"
                >
                  <Save className="w-4 h-4" />
                  Save Member
                </button>
                <button
                  onClick={() => setShowAddMember(false)}
                  className="px-4 py-2 bg-light-border dark:bg-dark-border text-light-text dark:text-dark-text rounded-lg hover:bg-light-border/80 dark:hover:bg-dark-border/80 transition"
                >
                  Cancel
                </button>
              </div>
            </motion.div>
          )}

          <div className="space-y-3">
            {filteredMembers.map((member) => (
              <motion.div
                key={member.id}
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                className="flex items-center justify-between p-4 bg-light-surface dark:bg-dark-surface rounded-xl border border-light-border dark:border-dark-border hover:shadow-md transition-shadow"
              >
                {editingMember === member.id ? (
                  <div className="flex-1 grid grid-cols-1 md:grid-cols-4 gap-2">
                    <input
                      type="text"
                      value={newMember.name || member.name}
                      onChange={(e) => setNewMember({ ...newMember, name: e.target.value })}
                      className="px-3 py-2 bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text"
                    />
                    <input
                      type="email"
                      value={newMember.email || member.email}
                      onChange={(e) => setNewMember({ ...newMember, email: e.target.value })}
                      className="px-3 py-2 bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text"
                    />
                    <input
                      type="text"
                      value={newMember.slack_handle || member.slack_handle}
                      onChange={(e) => setNewMember({ ...newMember, slack_handle: e.target.value })}
                      className="px-3 py-2 bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text"
                    />
                    <select
                      value={newMember.role || member.role}
                      onChange={(e) => setNewMember({ ...newMember, role: e.target.value })}
                      className="px-3 py-2 bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text"
                    >
                      <option value="primary">Primary</option>
                      <option value="secondary">Secondary</option>
                      <option value="tertiary">Tertiary</option>
                    </select>
                  </div>
                ) : (
                  <div className="flex items-center gap-4">
                    <div className="w-12 h-12 rounded-full bg-gradient-to-br from-brand-primary/20 to-brand-secondary/20 flex items-center justify-center text-brand-primary font-bold border-2 border-brand-primary/30">
                      {member.name.charAt(0).toUpperCase()}
                    </div>
                    <div>
                      <p className="font-medium text-light-text dark:text-dark-text">{member.name}</p>
                      <p className="text-sm text-light-muted dark:text-dark-muted">{member.email} • {member.slack_handle}</p>
                    </div>
                  </div>
                )}
                <div className="flex items-center gap-4">
                  {editingMember === member.id ? (
                    <>
                      <button
                        onClick={() => updateTeamMember(member.id)}
                        className="p-2 bg-brand-success/20 text-brand-success hover:bg-brand-success/30 rounded-lg transition"
                      >
                        <Save className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => {
                          setEditingMember(null);
                          setNewMember({ role: 'secondary' });
                        }}
                        className="p-2 bg-light-border dark:bg-dark-border text-light-muted dark:text-dark-muted hover:bg-light-border/80 dark:hover:bg-dark-border/80 rounded-lg transition"
                      >
                        <X className="w-4 h-4" />
                      </button>
                    </>
                  ) : (
                    <>
                      <span className={`px-3 py-1 rounded-full text-xs font-medium ${
                        member.role === 'primary' ? 'bg-brand-primary/20 text-brand-primary border border-brand-primary/30' :
                        member.role === 'secondary' ? 'bg-brand-secondary/20 text-brand-secondary border border-brand-secondary/30' :
                        'bg-light-border dark:bg-dark-border text-light-muted dark:text-dark-muted border border-light-border dark:border-dark-border'
                      }`}>
                        {member.role}
                      </span>
                      <button
                        onClick={() => {
                          setEditingMember(member.id);
                          setNewMember(member);
                        }}
                        className="p-2 text-light-muted dark:text-dark-muted hover:text-brand-primary hover:bg-brand-primary/10 rounded-lg transition"
                      >
                        <Edit className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => removeTeamMember(member.id)}
                        className="p-2 text-severity-critical hover:bg-severity-critical/10 rounded-lg transition"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </>
                  )}
                </div>
              </motion.div>
            ))}
            {filteredMembers.length === 0 && (
              <div className="text-center py-8">
                <Users className="w-8 h-8 text-light-muted dark:text-dark-muted mx-auto mb-2 opacity-50" />
                <p className="text-light-muted dark:text-dark-muted">No team members found</p>
              </div>
            )}
          </div>
        </motion.div>
      )}

      {/* Services Tab */}
      {activeTab === 'services' && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="bg-gradient-to-br from-light-card to-light-surface dark:from-dark-card dark:to-dark-surface rounded-2xl border border-light-border dark:border-dark-border shadow-xl p-6 backdrop-blur-sm"
        >
          <div className="flex items-center justify-between mb-6">
            <div>
              <h2 className="text-xl font-semibold text-light-text dark:text-dark-text">Services</h2>
              <p className="text-sm text-light-muted dark:text-dark-muted">{filteredServices.length} services</p>
            </div>
            <button
              onClick={() => setShowAddService(true)}
              className="flex items-center gap-2 px-4 py-2 bg-brand-primary text-white rounded-lg hover:bg-brand-primary/90 transition shadow-md"
            >
              <Plus className="w-4 h-4" />
              Add Service
            </button>
          </div>

          {showAddService && (
            <motion.div
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              className="mb-6 p-6 bg-light-surface dark:bg-dark-surface rounded-xl border border-light-border dark:border-dark-border shadow-sm"
            >
              <h3 className="text-lg font-semibold text-light-text dark:text-dark-text mb-4">Add New Service</h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <input
                  type="text"
                  placeholder="Service Name"
                  value={newService.name || ''}
                  onChange={(e) => setNewService({ ...newService, name: e.target.value })}
                  className="px-4 py-2 bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text placeholder-light-muted dark:placeholder-dark-muted"
                />
                <input
                  type="text"
                  placeholder="GitHub Repo Name"
                  value={newService.repo_name || ''}
                  onChange={(e) => setNewService({ ...newService, repo_name: e.target.value })}
                  className="px-4 py-2 bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text placeholder-light-muted dark:placeholder-dark-muted"
                />
                <input
                  type="text"
                  placeholder="Description"
                  value={newService.description || ''}
                  onChange={(e) => setNewService({ ...newService, description: e.target.value })}
                  className="md:col-span-2 px-4 py-2 bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text placeholder-light-muted dark:placeholder-dark-muted"
                />
                <label className="flex items-center gap-2 text-light-text dark:text-dark-text">
                  <input
                    type="checkbox"
                    checked={newService.is_critical || false}
                    onChange={(e) => setNewService({ ...newService, is_critical: e.target.checked })}
                    className="w-4 h-4"
                  />
                  Critical Service
                </label>
              </div>
              <div className="flex gap-2 mt-4">
                <button
                  onClick={addService}
                  className="flex items-center gap-2 px-4 py-2 bg-brand-success text-white rounded-lg hover:bg-brand-success/90 transition shadow-md"
                >
                  <Save className="w-4 h-4" />
                  Save Service
                </button>
                <button
                  onClick={() => setShowAddService(false)}
                  className="px-4 py-2 bg-light-border dark:bg-dark-border text-light-text dark:text-dark-text rounded-lg hover:bg-light-border/80 dark:hover:bg-dark-border/80 transition"
                >
                  Cancel
                </button>
              </div>
            </motion.div>
          )}

          <div className="space-y-3">
            {filteredServices.map((service) => (
              <motion.div
                key={service.id}
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                className="p-4 bg-light-surface dark:bg-dark-surface rounded-xl border border-light-border dark:border-dark-border hover:shadow-md transition-shadow"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3 flex-1">
                    <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-brand-primary/20 to-brand-secondary/20 flex items-center justify-center text-brand-primary font-bold border-2 border-brand-primary/30">
                      {service.name.charAt(0).toUpperCase()}
                    </div>
                    <div className="flex-1">
                      <p className="font-medium text-light-text dark:text-dark-text">{service.name}</p>
                      <p className="text-sm text-light-muted dark:text-dark-muted">{service.description} • {service.repo_name}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    {service.is_critical && (
                      <span className="px-3 py-1 bg-severity-critical/20 text-severity-critical text-xs rounded-full border border-severity-critical/30">
                        Critical
                      </span>
                    )}
                    <button
                      onClick={() => removeService(service.id)}
                      className="p-2 text-severity-critical hover:bg-severity-critical/10 rounded-lg transition"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              </motion.div>
            ))}
            {filteredServices.length === 0 && (
              <div className="text-center py-8">
                <Server className="w-8 h-8 text-light-muted dark:text-dark-muted mx-auto mb-2 opacity-50" />
                <p className="text-light-muted dark:text-dark-muted">No services found</p>
              </div>
            )}
          </div>
        </motion.div>
      )}

      {/* Escalation Policies Tab */}
      {activeTab === 'escalation' && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="bg-gradient-to-br from-light-card to-light-surface dark:from-dark-card dark:to-dark-surface rounded-2xl border border-light-border dark:border-dark-border shadow-xl p-6 backdrop-blur-sm"
        >
          <div className="flex items-center justify-between mb-6">
            <div>
              <h2 className="text-xl font-semibold text-light-text dark:text-dark-text">Escalation Policies</h2>
              <p className="text-sm text-light-muted dark:text-dark-muted">{escalationPolicies.length} policies</p>
            </div>
            <button
              onClick={() => setShowAddPolicy(true)}
              className="flex items-center gap-2 px-4 py-2 bg-brand-primary text-white rounded-lg hover:bg-brand-primary/90 transition shadow-md"
            >
              <Plus className="w-4 h-4" />
              Add Policy
            </button>
          </div>

          {showAddPolicy && (
            <motion.div
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              className="mb-6 p-6 bg-light-surface dark:bg-dark-surface rounded-xl border border-light-border dark:border-dark-border shadow-sm"
            >
              <h3 className="text-lg font-semibold text-light-text dark:text-dark-text mb-4">Add New Escalation Policy</h3>
              <div className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <input
                    type="text"
                    placeholder="Policy Name"
                    value={newPolicy.name || ''}
                    onChange={(e) => setNewPolicy({ ...newPolicy, name: e.target.value })}
                    className="px-4 py-2 bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text placeholder-light-muted dark:placeholder-dark-muted"
                  />
                  <input
                    type="text"
                    placeholder="Description"
                    value={newPolicy.description || ''}
                    onChange={(e) => setNewPolicy({ ...newPolicy, description: e.target.value })}
                    className="px-4 py-2 bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text placeholder-light-muted dark:placeholder-dark-muted"
                  />
                </div>

                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <label className="text-sm font-medium text-light-text dark:text-dark-text">Escalation Levels</label>
                    <button
                      onClick={() => addPolicyLevel()}
                      className="flex items-center gap-1 px-3 py-1 text-sm bg-brand-primary/10 text-brand-primary rounded-lg hover:bg-brand-primary/20 transition"
                    >
                      <Plus className="w-3 h-3" />
                      Add Level
                    </button>
                  </div>

                  {(newPolicy.levels || []).map((level, idx) => (
                    <div key={idx} className="p-3 bg-light-bg dark:bg-dark-bg rounded-lg border border-light-border dark:border-dark-border space-y-2">
                      <div className="grid grid-cols-2 gap-2">
                        <div>
                          <label className="text-xs text-light-muted dark:text-dark-muted">Tier</label>
                          <input
                            type="number"
                            value={level.tier}
                            disabled
                            className="w-full px-2 py-1 bg-light-surface dark:bg-dark-surface border border-light-border dark:border-dark-border rounded text-light-text dark:text-dark-text text-sm"
                          />
                        </div>
                        <div>
                          <label className="text-xs text-light-muted dark:text-dark-muted">Delay (minutes)</label>
                          <input
                            type="number"
                            value={level.delay_minutes}
                            onChange={(e) => {
                              const levels = newPolicy.levels || [];
                              levels[idx] = { ...level, delay_minutes: parseInt(e.target.value) || 0 };
                              setNewPolicy({ ...newPolicy, levels });
                            }}
                            className="w-full px-2 py-1 bg-light-surface dark:bg-dark-surface border border-light-border dark:border-dark-border rounded text-light-text dark:text-dark-text text-sm"
                          />
                        </div>
                      </div>
                      <input
                        type="text"
                        placeholder="Members (comma-separated)"
                        value={level.members.join(', ')}
                        onChange={(e) => {
                          const levels = newPolicy.levels || [];
                          levels[idx] = { ...level, members: e.target.value.split(',').map(m => m.trim()) };
                          setNewPolicy({ ...newPolicy, levels });
                        }}
                        className="w-full px-2 py-1 bg-light-surface dark:bg-dark-surface border border-light-border dark:border-dark-border rounded text-light-text dark:text-dark-text text-sm placeholder-light-muted dark:placeholder-dark-muted"
                      />
                    </div>
                  ))}
                </div>

                <div className="flex gap-2">
                  <button
                    onClick={addEscalationPolicy}
                    className="flex items-center gap-2 px-4 py-2 bg-brand-success text-white rounded-lg hover:bg-brand-success/90 transition shadow-md"
                  >
                    <Save className="w-4 h-4" />
                    Save Policy
                  </button>
                  <button
                    onClick={() => setShowAddPolicy(false)}
                    className="px-4 py-2 bg-light-border dark:bg-dark-border text-light-text dark:text-dark-text rounded-lg hover:bg-light-border/80 dark:hover:bg-dark-border/80 transition"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            </motion.div>
          )}

          <div className="space-y-4">
            {escalationPolicies.map((policy) => (
              <motion.div
                key={policy.id}
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                className="p-6 bg-light-surface dark:bg-dark-surface rounded-xl border border-light-border dark:border-dark-border hover:shadow-md transition-shadow"
              >
                {editingPolicy === policy.id ? (
                  <div className="space-y-4">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <input
                        type="text"
                        value={newPolicy.name || policy.name}
                        onChange={(e) => setNewPolicy({ ...newPolicy, name: e.target.value })}
                        className="px-4 py-2 bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text"
                      />
                      <input
                        type="text"
                        value={newPolicy.description || policy.description}
                        onChange={(e) => setNewPolicy({ ...newPolicy, description: e.target.value })}
                        className="px-4 py-2 bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text"
                      />
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={() => updateEscalationPolicy(policy.id)}
                        className="flex items-center gap-2 px-4 py-2 bg-brand-success text-white rounded-lg hover:bg-brand-success/90 transition"
                      >
                        <Save className="w-4 h-4" />
                        Save Changes
                      </button>
                      <button
                        onClick={() => {
                          setEditingPolicy(null);
                          setNewPolicy({ name: '', description: '', levels: [] });
                        }}
                        className="px-4 py-2 bg-light-border dark:bg-dark-border text-light-text dark:text-dark-text rounded-lg hover:bg-light-border/80 dark:hover:bg-dark-border/80 transition"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    <div className="flex items-start justify-between mb-4">
                      <div>
                        <p className="font-semibold text-light-text dark:text-dark-text text-lg">{policy.name}</p>
                        <p className="text-sm text-light-muted dark:text-dark-muted">{policy.description}</p>
                      </div>
                      <div className="flex gap-2">
                        <button
                          onClick={() => {
                            setEditingPolicy(policy.id);
                            setNewPolicy(policy);
                          }}
                          className="p-2 text-light-muted dark:text-dark-muted hover:text-brand-primary hover:bg-brand-primary/10 rounded-lg transition"
                        >
                          <Edit className="w-4 h-4" />
                        </button>
                        <button
                          onClick={() => deleteEscalationPolicy(policy.id)}
                          className="p-2 text-severity-critical hover:bg-severity-critical/10 rounded-lg transition"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    </div>

                    <div className="space-y-2">
                      {policy.levels.map((level, idx) => (
                        <div key={idx} className="flex items-center gap-3 p-3 bg-light-bg dark:bg-dark-bg rounded-lg border border-light-border dark:border-dark-border">
                          <div className="flex items-center justify-center w-8 h-8 bg-brand-primary text-white rounded-full text-sm font-bold">
                            L{level.tier}
                          </div>
                          <div className="flex-1">
                            <p className="text-sm font-medium text-light-text dark:text-dark-text">
                              {level.members.join(', ')}
                            </p>
                            <div className="flex items-center gap-1 text-xs text-light-muted dark:text-dark-muted">
                              <Clock className="w-3 h-3" />
                              After {level.delay_minutes} minutes
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </motion.div>
            ))}
            {escalationPolicies.length === 0 && (
              <div className="text-center py-8">
                <AlertCircle className="w-8 h-8 text-light-muted dark:text-dark-muted mx-auto mb-2 opacity-50" />
                <p className="text-light-muted dark:text-dark-muted">No escalation policies found</p>
              </div>
            )}
          </div>
        </motion.div>
      )}
    </div>
  );
}
