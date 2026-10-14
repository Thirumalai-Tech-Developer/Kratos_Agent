import React, { useState } from 'react';
import { Wrench, ChevronRight, CheckCircle2, CircleAlert, LoaderCircle, Square, Terminal } from 'lucide-react';

const STATUSES = {
  running: ['Running', LoaderCircle], completed: ['Completed', CheckCircle2],
  failed: ['Failed', CircleAlert], cancelled: ['Stopped', Square], unknown: ['Result unavailable', CircleAlert],
};
function format(value) { return typeof value === 'string' ? value : JSON.stringify(value, null, 2) || ''; }

function ToolCallCard({ item }) {
  // Keep an explicitly expanded call open when its result arrives.
  const [isOpen, setIsOpen] = useState(false);
  const [label, Icon] = STATUSES[item.status] || STATUSES.unknown;
  return <details className={`tool-card tool-${item.status}`} open={isOpen} onToggle={event => setIsOpen(event.currentTarget.open)}>
      <summary aria-label={`${item.name}: ${label}`}><ChevronRight className="tool-chevron" size={14} /><Wrench size={14} />
        <span className="tool-label"><strong>{item.name}</strong>{item.label && item.label !== item.name && <small>{item.label}</small>}</span>
        {item.source_agent?.role && <small className="tool-agent-label">{item.source_agent.role}</small>}
        <span className="tool-state" role="status" aria-live="polite"><Icon size={13} className={item.status === 'running' ? 'animate-spin' : ''} />{label}</span>
      </summary>
      <div className="tool-details">
        {item.arguments !== undefined && <section><h3>Arguments</h3><pre>{format(item.arguments)}</pre></section>}
        {item.output !== undefined && <section><h3>Result{item.truncated ? ' (preview)' : ''}</h3><pre>{format(item.output)}</pre></section>}
        {item.status === 'running' && <p>Waiting for the tool to return.</p>}
        {item.status_detail && <p>{item.status_detail}</p>}
        {item.status === 'unknown' && item.output === undefined && <p>The saved activity does not include a result.</p>}
      </div>
    </details>;
}

function groupState(activities) {
  const running = activities.filter(item => item.status === 'running').length;
  if (running) return ['running', `${running} running`, LoaderCircle];
  const failed = activities.filter(item => item.status === 'failed').length;
  if (failed) return ['failed', `${failed} failed`, CircleAlert];
  const stopped = activities.filter(item => item.status === 'cancelled').length;
  if (stopped) return ['cancelled', `${stopped} stopped`, Square];
  if (activities.every(item => item.status === 'completed')) return ['completed', 'Completed', CheckCircle2];
  return ['unknown', 'Result unavailable', CircleAlert];
}

export default function ToolActivity({ activities = [], grouped = true, anchors = {} }) {
  const [isOpen, setIsOpen] = useState(false);
  if (!activities.length) return null;
  const [status, label, Icon] = groupState(activities);
  const cards = <div className="tool-activity" aria-label="Tool activity">{activities.map(item =>
    <div className="timeline-tool" id={anchors[item.id]} key={item.id}><ToolCallCard item={item} /></div>
  )}</div>;
  if (!grouped) return cards;
  return <details className={`tool-activity-group group-${status}`} open={isOpen} onToggle={event => setIsOpen(event.currentTarget.open)}>
    <summary aria-label={`${activities.length} tool ${activities.length === 1 ? 'call' : 'calls'}: ${label}`}>
      <ChevronRight size={14} /><Terminal size={14} />
      <span className="tool-group-label">{activities.length} tool {activities.length === 1 ? 'call' : 'calls'}<small>{isOpen ? 'Hide details' : 'Show details'}</small></span>
      <span className="tool-group-state" role="status" aria-live="polite"><Icon size={13} className={status === 'running' ? 'animate-spin' : ''} />{label}</span>
    </summary>{cards}
  </details>;
}
