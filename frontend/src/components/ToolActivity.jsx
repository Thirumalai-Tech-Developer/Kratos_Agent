import React from 'react';
import { Wrench, ChevronRight, CheckCircle2, CircleAlert, LoaderCircle, Square } from 'lucide-react';

const STATUSES = {
  running: ['Running', LoaderCircle], completed: ['Completed', CheckCircle2],
  failed: ['Failed', CircleAlert], cancelled: ['Stopped', Square], unknown: ['Result unavailable', CircleAlert],
};

function format(value) {
  if (typeof value === 'string') return value;
  return JSON.stringify(value, null, 2) || '';
}

export default function ToolActivity({ activities = [] }) {
  if (!activities.length) return null;
  return <div className="tool-activity" aria-label="Tool activity">
    {activities.map(item => {
      const [label, Icon] = STATUSES[item.status] || STATUSES.unknown;
      return <details key={item.id} className={`tool-card tool-${item.status}`}>
        <summary aria-label={`${item.name}: ${label}`}>
          <ChevronRight className="tool-chevron" size={15} />
          <Wrench size={15} />
          <span className="tool-label"><strong>{item.name}</strong>{item.label !== item.name && <small>{item.label}</small>}</span>
          <span className="tool-state"><Icon size={14} className={item.status === 'running' ? 'animate-spin' : ''} />{label}</span>
        </summary>
        <div className="tool-details">
          {item.arguments !== undefined && <section><h3>Arguments</h3><pre>{format(item.arguments)}</pre></section>}
          {item.output !== undefined && <section><h3>Result{item.truncated ? ' (preview)' : ''}</h3><pre>{format(item.output)}</pre></section>}
          {item.status === 'running' && <p>Waiting for the tool to return.</p>}
          {item.status === 'unknown' && item.output === undefined && <p>The saved activity does not include a result.</p>}
        </div>
      </details>;
    })}
  </div>;
}
