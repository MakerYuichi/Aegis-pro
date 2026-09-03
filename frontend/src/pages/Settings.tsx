import { useState } from 'react';
import { Users, Server, Plus, Trash2, Save } from 'lucide-react';

interface TeamMember {
  id: string;
  name: string;
  email: string;
  role: string;
  slack_handle: string;
}

interface Service {
  id: string;
  name: string;
  description: string;
  repo_name: string;
  dependencies: string[];
  is_critical: boolean;
}

export function Settings() {
  const [teamMembers, setTeamMembers] = useState<TeamMember[]>([
    { id: '1', name: 'Rahul Kumar', email: 'rahul@example.com', role: 'primary', slack_handle: '@rahul' },
    { id: '2', name: 'Priya Sharma', email: 'priya@example.com', role: 'secondary', slack_handle: '@priya' },
  ]);

  const [services, setServices] = useState<Service[]>([
    { id: '1', name: 'payment-api', description: 'Payment processing', repo_name: 'fastapi', dependencies: ['auth', 'ledger'], is_critical: true },
    { id: '2', name: 'auth', description: 'Authentication', repo_name: 'auth-service', dependencies: [], is_critical: true },
  ]);

  const [newMember, setNewMember] = useState<Partial<TeamMember>>({ role: 'secondary' });
  const [newService, setNewService] = useState<Partial<Service>>({ is_critical: false, dependencies: [] });
  const [showAddMember, setShowAddMember] = useState(false);
  const [showAddService, setShowAddService] = useState(false);

  const addTeamMember = () => {
    if (newMember.name && newMember.email) {
      const member: TeamMember = {
        id: Date.now().toString(),
        name: newMember.name,
        email: newMember.email,
        role: newMember.role || 'secondary',
        slack_handle: newMember.slack_handle || ''
      };
      setTeamMembers([...teamMembers, member]);
      setNewMember({ role: 'secondary' });
      setShowAddMember(false);
    }
  };

  const removeTeamMember = (id: string) => {
    setTeamMembers(teamMembers.filter(m => m.id !== id));
  };

  const addService = () => {
    if (newService.name && newService.repo_name) {
      const service: Service = {
        id: Date.now().toString(),
        name: newService.name,
        description: newService.description || '',
        repo_name: newService.repo_name,
        dependencies: newService.dependencies || [],
        is_critical: newService.is_critical || false
      };
      setServices([...services, service]);
      setNewService({ is_critical: false, dependencies: [] });
      setShowAddService(false);
    }
  };

  const removeService = (id: string) => {
    setServices(services.filter(s => s.id !== id));
  };

  const removeDependency = (serviceId: string, dep: string) => {
    setServices(services.map(s => 
      s.id === serviceId 
        ? { ...s, dependencies: s.dependencies.filter(d => d !== dep) }
        : s
    ));
  };

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold text-light-text dark:text-dark-text">Settings</h1>
        <p className="text-light-muted dark:text-dark-muted">Manage team members and services</p>
      </div>

      {/* Team Members Section */}
      <div className="bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border shadow-lg p-6">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-2">
            <Users className="w-5 h-5 text-brand-primary" />
            <h2 className="text-xl font-semibold text-light-text dark:text-dark-text">Team Members</h2>
          </div>
          <button
            onClick={() => setShowAddMember(true)}
            className="flex items-center gap-2 px-4 py-2 bg-brand-primary text-white rounded-lg hover:bg-brand-primary/90 transition"
          >
            <Plus className="w-4 h-4" />
            Add Member
          </button>
        </div>

        {showAddMember && (
          <div className="mb-6 p-4 bg-light-surface dark:bg-dark-surface rounded-lg border border-light-border dark:border-dark-border">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <input
                type="text"
                placeholder="Name"
                value={newMember.name || ''}
                onChange={(e) => setNewMember({ ...newMember, name: e.target.value })}
                className="px-3 py-2 bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text"
              />
              <input
                type="email"
                placeholder="Email"
                value={newMember.email || ''}
                onChange={(e) => setNewMember({ ...newMember, email: e.target.value })}
                className="px-3 py-2 bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text"
              />
              <input
                type="text"
                placeholder="Slack Handle"
                value={newMember.slack_handle || ''}
                onChange={(e) => setNewMember({ ...newMember, slack_handle: e.target.value })}
                className="px-3 py-2 bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text"
              />
              <select
                value={newMember.role || 'secondary'}
                onChange={(e) => setNewMember({ ...newMember, role: e.target.value })}
                className="px-3 py-2 bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text"
              >
                <option value="primary">Primary</option>
                <option value="secondary">Secondary</option>
                <option value="tertiary">Tertiary</option>
              </select>
            </div>
            <div className="flex gap-2 mt-4">
              <button
                onClick={addTeamMember}
                className="flex items-center gap-2 px-4 py-2 bg-brand-success text-white rounded-lg hover:bg-brand-success/90 transition"
              >
                <Save className="w-4 h-4" />
                Save
              </button>
              <button
                onClick={() => setShowAddMember(false)}
                className="px-4 py-2 bg-light-border dark:bg-dark-border text-light-text dark:text-dark-text rounded-lg hover:bg-light-border/80 dark:hover:bg-dark-border/80 transition"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        <div className="space-y-3">
          {teamMembers.map((member) => (
            <div
              key={member.id}
              className="flex items-center justify-between p-4 bg-light-surface dark:bg-dark-surface rounded-lg border border-light-border dark:border-dark-border"
            >
              <div className="flex items-center gap-4">
                <div className="w-10 h-10 rounded-full bg-brand-primary/20 flex items-center justify-center text-brand-primary font-bold">
                  {member.name.charAt(0).toUpperCase()}
                </div>
                <div>
                  <p className="font-medium text-light-text dark:text-dark-text">{member.name}</p>
                  <p className="text-sm text-light-muted dark:text-dark-muted">{member.email} • {member.slack_handle}</p>
                </div>
              </div>
              <div className="flex items-center gap-4">
                <span className={`px-2 py-1 rounded text-xs ${
                  member.role === 'primary' ? 'bg-brand-primary/20 text-brand-primary' :
                  member.role === 'secondary' ? 'bg-brand-secondary/20 text-brand-secondary' :
                  'bg-light-border dark:bg-dark-border text-light-muted dark:text-dark-muted'
                }`}>
                  {member.role}
                </span>
                <button
                  onClick={() => removeTeamMember(member.id)}
                  className="p-2 text-severity-critical hover:bg-severity-critical/10 rounded-lg transition"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Services Section */}
      <div className="bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border shadow-lg p-6">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-2">
            <Server className="w-5 h-5 text-brand-primary" />
            <h2 className="text-xl font-semibold text-light-text dark:text-dark-text">Services</h2>
          </div>
          <button
            onClick={() => setShowAddService(true)}
            className="flex items-center gap-2 px-4 py-2 bg-brand-primary text-white rounded-lg hover:bg-brand-primary/90 transition"
          >
            <Plus className="w-4 h-4" />
            Add Service
          </button>
        </div>

        {showAddService && (
          <div className="mb-6 p-4 bg-light-surface dark:bg-dark-surface rounded-lg border border-light-border dark:border-dark-border">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <input
                type="text"
                placeholder="Service Name"
                value={newService.name || ''}
                onChange={(e) => setNewService({ ...newService, name: e.target.value })}
                className="px-3 py-2 bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text"
              />
              <input
                type="text"
                placeholder="GitHub Repo Name"
                value={newService.repo_name || ''}
                onChange={(e) => setNewService({ ...newService, repo_name: e.target.value })}
                className="px-3 py-2 bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text"
              />
              <input
                type="text"
                placeholder="Description"
                value={newService.description || ''}
                onChange={(e) => setNewService({ ...newService, description: e.target.value })}
                className="md:col-span-2 px-3 py-2 bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text"
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
                className="flex items-center gap-2 px-4 py-2 bg-brand-success text-white rounded-lg hover:bg-brand-success/90 transition"
              >
                <Save className="w-4 h-4" />
                Save
              </button>
              <button
                onClick={() => setShowAddService(false)}
                className="px-4 py-2 bg-light-border dark:bg-dark-border text-light-text dark:text-dark-text rounded-lg hover:bg-light-border/80 dark:hover:bg-dark-border/80 transition"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        <div className="space-y-3">
          {services.map((service) => (
            <div
              key={service.id}
              className="p-4 bg-light-surface dark:bg-dark-surface rounded-lg border border-light-border dark:border-dark-border"
            >
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-brand-primary/20 flex items-center justify-center text-brand-primary font-bold">
                    {service.name.charAt(0).toUpperCase()}
                  </div>
                  <div>
                    <p className="font-medium text-light-text dark:text-dark-text">{service.name}</p>
                    <p className="text-sm text-light-muted dark:text-dark-muted">{service.description}</p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  {service.is_critical && (
                    <span className="px-2 py-1 bg-severity-critical/20 text-severity-critical text-xs rounded">
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
              <div className="space-y-2">
                <p className="text-xs text-light-muted dark:text-dark-muted">Repo: {service.repo_name}</p>
                {service.dependencies.length > 0 && (
                  <div>
                    <p className="text-xs text-light-muted dark:text-dark-muted mb-1">Dependencies:</p>
                    <div className="flex flex-wrap gap-2">
                      {service.dependencies.map((dep) => (
                        <span
                          key={dep}
                          className="flex items-center gap-1 px-2 py-1 bg-light-bg dark:bg-dark-bg text-xs rounded border border-light-border dark:border-dark-border"
                        >
                          {dep}
                          <button
                            onClick={() => removeDependency(service.id, dep)}
                            className="text-light-muted dark:text-dark-muted hover:text-severity-critical"
                          >
                            ×
                          </button>
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}