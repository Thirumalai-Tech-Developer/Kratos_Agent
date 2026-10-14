import React, { useState } from 'react';
import { Minimize2, ChevronDown, LoaderCircle } from 'lucide-react';
import { contextUsageView, formatContextTokens as tokens } from '../contextUsage';

export default function ContextMeter({ context, isExecuting, isCompacting, onCompact, notice, error }) {
  const [expanded, setExpanded] = useState(false);
  const view = contextUsageView(context);
  const disabled = isExecuting || isCompacting || context?.busy || !context?.can_compact;
  return (
    <div className={`context-meter context-${view?.tone || 'normal'}`}>
      <div className="context-meter-row">
        <button type="button" className="context-details-toggle" onClick={() => setExpanded(!expanded)} aria-expanded={expanded} aria-controls="context-details">
          <span>Context</span>
          <strong>{view ? `${view.estimated ? '~' : ''}${tokens(view.used)} / ${tokens(context.input_limit)} tokens` : 'Waiting for runtime'}</strong>
          {view && <span>{view.percent}%</span>}
          <ChevronDown size={13} style={{ transform: expanded ? 'rotate(180deg)' : undefined }} />
        </button>
        <button type="button" className="context-compact-button" onClick={onCompact} disabled={disabled}
          title={isExecuting || context?.busy ? 'Finish or stop the active task before compacting' : 'Summarize older working context. Full conversation stays saved.'}>
          {isCompacting ? <LoaderCircle size={13} className="animate-spin" /> : <Minimize2 size={13} />}
          {isCompacting ? 'Compacting…' : 'Compact context'}
        </button>
      </div>
      {view && <div className="context-progress" role="progressbar" aria-label="Input context used" aria-valuemin={0} aria-valuemax={100} aria-valuenow={view.progress} aria-valuetext={`${view.percent}% used; ${view.estimated ? 'estimated' : 'provider reported'}`}>
        <span style={{ width: `${view.progress}%` }} />
      </div>}
      {expanded && <div id="context-details" className="context-details">
        {view ? <>
          <span>Window <strong>{tokens(context.context_limit)}</strong> · Output reserve <strong>{tokens(context.reserved_output_tokens)}</strong> · Available input <strong>{tokens(view.remaining)}</strong></span>
          <span>{view.estimated ? 'Estimated working context' : 'Provider reported input'} · {context.limit_source === 'model' ? 'Model limit' : 'Configured limit; provider has not reported its limit'} · Auto compaction at {tokens(context.auto_compact_at_tokens)} input tokens (90%)</span>
          {!context.overhead_known && <span>History estimate only. Instructions and tools are included after the first model request.</span>}
          {Number.isFinite(context.provider_input_tokens) && <span>Last request input: {tokens(context.provider_input_tokens)} tokens, reported by provider</span>}
          {context.last_compaction ? <span>Compacted {context.compaction_count} {context.compaction_count === 1 ? 'time' : 'times'} · {context.last_compaction.reason === 'manual' ? 'Manual' : 'Automatic'} · {tokens(context.last_compaction.before_tokens)} → {tokens(context.last_compaction.after_tokens)} · Saved {tokens(view.lastSaved)} tokens</span> : <span>No compaction yet in this session.</span>}
          <span>Compaction preserves the latest request and recent results. Full conversation remains saved.</span>
        </> : <span>Context information will appear when the runtime connects.</span>}
      </div>}
      {(error || notice || (view && context.over_limit)) && <p className={`context-notice ${error || context?.over_limit ? 'context-error' : ''}`} role="status">
        {error || notice || 'Context exceeds the input budget. Compact context before continuing.'}
      </p>}
    </div>
  );
}
