import React, { useState } from 'react';
import { Zap, Activity, Cpu, Wrench, ShieldCheck, ListOrdered, FileJson, Clock } from 'lucide-react';

const FILTERS = [
  { id: 'all', label: 'All Events' },
  { id: 'tool', label: 'Tools' },
  { id: 'model', label: 'Model' },
  { id: 'task', label: 'Tasks & Plan' },
  { id: 'verification', label: 'Verification' }
];

export default function TraceReplay({ events, onInspectPayload, isLoading }) {
  const [activeFilter, setActiveFilter] = useState('all');

  const filteredEvents = (events || []).filter(e => {
    if (activeFilter === 'all') return true;
    const kind = (e.kind || '').toLowerCase();
    if (activeFilter === 'tool') return kind.includes('tool');
    if (activeFilter === 'model') return kind.includes('model') || kind.includes('token') || kind.includes('llm');
    if (activeFilter === 'task') return kind.includes('task') || kind.includes('plan');
    if (activeFilter === 'verification') return kind.includes('verify') || kind.includes('test');
    return true;
  });

  const getEventIcon = (kind) => {
    const k = (kind || '').toLowerCase();
    if (k.includes('tool')) return <Wrench className="w-4 h-4 text-cyan-400" />;
    if (k.includes('model') || k.includes('token')) return <Cpu className="w-4 h-4 text-pink-400" />;
    if (k.includes('verify') || k.includes('test')) return <ShieldCheck className="w-4 h-4 text-emerald-400" />;
    if (k.includes('plan') || k.includes('task')) return <ListOrdered className="w-4 h-4 text-amber-400" />;
    return <Zap className="w-4 h-4 text-purple-400" />;
  };

  return (
    <div className="flex flex-col h-full min-h-0 glass-panel rounded-2xl border border-pink-500/20 overflow-hidden shadow-xl p-4 sm:p-6">
      
      {/* Top Toolbar */}
      <div className="flex-shrink-0 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 pb-4 mb-4 border-b border-white/10">
        
        {/* Filter Chips */}
        <div className="flex flex-wrap items-center gap-2">
          {FILTERS.map((f) => (
            <button
              key={f.id}
              onClick={() => setActiveFilter(f.id)}
              className={`px-3 py-1 rounded-full text-xs font-pixl font-bold tracking-wider transition ${
                activeFilter === f.id
                  ? 'bg-gradient-to-r from-[#ff007f] to-[#ff8c00] text-white shadow-[0_0_12px_rgba(255,0,127,0.4)]'
                  : 'bg-black/40 border border-white/10 text-slate-300 hover:border-pink-500/40'
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>

        <div className="text-xs font-code text-slate-400 flex items-center gap-1.5">
          <Clock className="w-3.5 h-3.5 text-cyan-400" />
          <span>{filteredEvents.length} events loaded from D1</span>
        </div>
      </div>

      {/* Events Timeline */}
      <div className="flex-1 min-h-0 overflow-y-auto space-y-3 pr-1 scrollbar-thin">
        {isLoading ? (
          <div className="p-12 text-center text-xs text-slate-500">Loading trace events from D1...</div>
        ) : filteredEvents.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center text-slate-500 py-12">
            <Activity className="w-12 h-12 text-slate-600 mb-3" />
            <h3 className="font-orbitron font-bold text-sm text-slate-400">No trace events found</h3>
            <p className="text-xs text-slate-500 mt-1 max-w-sm">
              Agentic runtime events will appear here as Kratos executes autonomous steps.
            </p>
          </div>
        ) : (
          filteredEvents.map((evt, idx) => {
            let payloadObj = null;
            try {
              payloadObj = typeof evt.payload_json === 'string' ? JSON.parse(evt.payload_json) : evt.payload_json;
            } catch (_) {
              payloadObj = evt.payload_json;
            }

            return (
              <div
                key={evt.id || idx}
                className="p-3.5 rounded-xl bg-black/40 border border-white/5 hover:border-pink-500/30 transition flex items-start justify-between gap-3 text-xs"
              >
                <div className="flex items-start gap-3">
                  <div className="p-2 rounded-lg bg-slate-900 border border-white/10 mt-0.5">
                    {getEventIcon(evt.kind)}
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-code font-bold text-slate-100 uppercase tracking-wide">
                        {evt.kind}
                      </span>
                      <span className="text-[10px] font-code text-slate-500">
                        {evt.timestamp ? new Date(evt.timestamp * 1000).toLocaleTimeString() : ''}
                      </span>
                    </div>

                    <p className="text-slate-400 font-sans mt-1 line-clamp-2">
                      {payloadObj?.message || payloadObj?.label || JSON.stringify(payloadObj || {})}
                    </p>
                  </div>
                </div>

                <button
                  onClick={() => onInspectPayload(evt)}
                  className="px-2.5 py-1 rounded-lg text-[10.5px] font-pixl flex items-center gap-1 bg-slate-800/80 hover:bg-pink-950/40 border border-slate-700/60 hover:border-pink-500/40 text-slate-300 hover:text-pink-300 transition whitespace-nowrap"
                  title="Inspect raw event JSON payload"
                >
                  <FileJson className="w-3.5 h-3.5 text-cyan-400" />
                  <span>PAYLOAD</span>
                </button>
              </div>
            );
          })
        )}
      </div>

    </div>
  );
}
