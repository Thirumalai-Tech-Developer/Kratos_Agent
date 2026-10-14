import React, { useState } from 'react';
import { Terminal, Users, ListChecks, X, CircleCheck, CircleAlert, LoaderCircle, Circle, ArrowUpRight } from 'lucide-react';
import { latestPlan, subagentReports, subagentToolActivities } from '../workspaceActivity';
import MarkdownRenderer from './MarkdownRenderer';
import KratosMark from './KratosMark';

function stateView(state) {
  const status = String(state || 'unknown').toLowerCase();
  if (['completed', 'complete', 'done'].includes(status)) return ['Completed', CircleCheck];
  if (['running', 'executing', 'in_progress'].includes(status)) return ['Running', LoaderCircle];
  if (['failed', 'needs_attention', 'blocked'].includes(status)) return ['Needs attention', CircleAlert];
  if (['cancelled', 'stopped'].includes(status)) return ['Stopped', Circle];
  if (status === 'paused') return ['Paused', Circle];
  if (status === 'pending') return ['Pending', Circle];
  return ['Status not reported', Circle];
}

export default function AgentHud({ currentStep, activities = [], events = [], availableTools = [], isExecuting, sessionStatus, telemetry, isOpen, onClose, onOpenActivity, onFocusTool }) {
  const [tab, setTab] = useState('commands');
  const agents = subagentReports(events, activities);
  const plan = latestPlan(events);
  const completed = plan.tasks.filter(task => String(task.state || task.status).toLowerCase() === 'completed').length;
  if (!isOpen) return null;
  const tabs = [['commands', 'Commands', Terminal, activities.length], ['subagents', 'Subagents', Users, agents.length], ['task', 'Task', ListChecks, plan.tasks.length]];
  return <section className="task-details task-details-inline" aria-label="Task details">
      <header className="details-header"><span>Workspace details</span><button className="studio-icon" type="button" onClick={onClose} aria-label="Close task details"><X size={16} /></button></header>
      <div className="details-tabs" role="tablist" aria-label="Task detail sections">
        {tabs.map(([id, label, Icon, count]) => <button key={id} type="button" role="tab" aria-selected={tab === id} aria-controls={`details-${id}`} id={`details-tab-${id}`} onClick={() => setTab(id)}><Icon size={14} /><span>{label}</span>{count > 0 && <small>{count}</small>}</button>)}
      </div>
      <div className="details-content" role="tabpanel" id={`details-${tab}`} aria-labelledby={`details-tab-${tab}`}>
        {tab === 'commands' && <>
          <div className="details-section-heading"><h2>Tool activity</h2><span>{activities.length} {activities.length === 1 ? 'action' : 'actions'}</span></div>
          {activities.length ? <ul className="details-command-summary">{activities.map(activity => <li key={activity.id}><button type="button" onClick={() => onFocusTool?.(activity.id)}>
            <span>{activity.source_agent?.role && <small>{activity.source_agent.role} · </small>}{activity.name}</span><small>{stateView(activity.status)[0]}<ArrowUpRight size={12} /></small>
          </button></li>)}</ul> : <div className="details-empty"><Terminal size={25} /><strong>No commands yet</strong><p>File operations, browser actions, and commands appear here as they run.</p></div>}
        </>}
        {tab === 'subagents' && <>
          <div className="details-section-heading"><h2>Delegated work</h2><span>{agents.filter(agent => agent.status === 'running').length} running</span></div>
          {agents.length ? agents.map(agent => {
            const [label, Icon] = stateView(agent.status);
            return <details className={`subagent-card agent-${agent.status || 'unknown'}`} key={agent.id} open={agent.status === 'running' || undefined}>
              <summary><KratosMark size={25} title="" /><span><strong>{agent.role || 'Subagent'}</strong><small>{agent.task || 'Delegated task'}</small></span><Icon size={15} className={agent.status === 'running' ? 'animate-spin' : ''} /></summary>
              <div className="subagent-report"><div className="subagent-report-meta"><span>{label}</span>{typeof agent.duration_ms === 'number' && <span>{(agent.duration_ms / 1000).toFixed(1)}s</span>}</div>
                {agent.summary && <MarkdownRenderer content={agent.summary} />}
                {agent.error && <p className="subagent-error">{String(agent.error)}</p>}
                {subagentToolActivities(agent).length > 0 && <ul className="details-command-summary">{subagentToolActivities(agent).map(activity => <li key={activity.id}><button type="button" onClick={() => onFocusTool?.(`${agent.id}:${activity.id}`)}>
                  <span>{activity.name}</span><small>{stateView(activity.status)[0]}<ArrowUpRight size={12} /></small>
                </button></li>)}</ul>}
                {!agent.summary && !agent.error && agent.status !== 'running' && <p className="details-muted">No report was included in this event.</p>}
              </div>
            </details>;
          }) : <div className="details-empty"><Users size={25} /><strong>No subagents in this chat</strong><p>Delegated tasks and their reports appear here when Kratos uses subagents.</p></div>}
        </>}
        {tab === 'task' && <>
          <div className="task-state-summary"><span className={isExecuting ? 'is-running' : ''}><i />{isExecuting ? 'In progress' : sessionStatus ? stateView(sessionStatus)[0] : 'Ready'}</span><p>{currentStep?.label || plan.goal || 'Start a conversation to create a task.'}</p></div>
          {plan.tasks.length > 0 && <>
            <div className="details-section-heading"><h2>Plan</h2><span>{completed} / {plan.tasks.length}</span></div>
            <ol className="details-plan">{plan.tasks.map((task, index) => {
              const [label, Icon] = stateView(task.state || task.status);
              return <li key={task.id || task.title || index}><Icon size={16} className={label === 'Running' ? 'animate-spin' : ''} /><span><strong>{task.title || task.description || `Task ${index + 1}`}</strong><small>{label}</small>{task.result && <p>{String(task.result)}</p>}</span></li>;
            })}</ol>
          </>}
          <dl className="details-workspace-metadata">{telemetry?.model && <><dt>Model</dt><dd>{telemetry.normal_mode_model || telemetry.model}</dd></>}{telemetry?.workspace && <><dt>Workspace</dt><dd>{String(telemetry.workspace)}</dd></>}</dl>
          {availableTools.length > 0 && <details className="details-available-tools"><summary>Available tools <span>{availableTools.length}</span></summary><ul>{availableTools.map(tool => <li key={tool.name}><strong>{tool.name}</strong><small>{tool.description}</small></li>)}</ul></details>}
          <button className="details-activity-link" type="button" onClick={onOpenActivity}>View full activity<ArrowUpRight size={14} /></button>
        </>}
      </div>
    </section>;
}
