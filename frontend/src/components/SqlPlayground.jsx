import React, { useState } from 'react';
import { Play, Database, Table, Clock, AlertCircle } from 'lucide-react';

const PRESETS = [
  { label: 'Recent Sessions', sql: 'SELECT * FROM sessions ORDER BY updated_at DESC LIMIT 10;' },
  { label: 'Latest Turns', sql: 'SELECT id, session_id, turn_index, user_query, timestamp FROM turns ORDER BY timestamp DESC LIMIT 20;' },
  { label: 'Event Breakdown', sql: 'SELECT kind, COUNT(*) as total_events FROM agentic_events GROUP BY kind ORDER BY total_events DESC;' },
  { label: 'Shell Commands', sql: 'SELECT * FROM commands ORDER BY timestamp DESC LIMIT 15;' }
];

export default function SqlPlayground({ onExecuteQuery, results, isLoading, error }) {
  const [query, setQuery] = useState(PRESETS[0].sql);

  const handleKeyDown = (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      onExecuteQuery(query);
    }
  };

  const columns = results?.length > 0 ? Object.keys(results[0]) : [];

  return (
    <div className="flex flex-col h-full min-h-0 glass-panel rounded-2xl border border-pink-500/20 overflow-hidden shadow-xl p-4 sm:p-6 space-y-4">
      
      {/* Top Header & Presets */}
      <div className="flex-shrink-0">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2 text-xs font-rajdhani font-bold text-slate-300">
            <Database className="w-4 h-4 text-cyan-400" />
            <span>CLOUDFLARE D1 SQL PLAYGROUND</span>
          </div>
          <span className="text-[11px] font-code text-slate-500 hidden sm:inline">
            Direct SQL read queries on serverless D1
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-1.5 pt-1">
          <span className="text-xs font-pixl font-bold text-slate-400 mr-1">PRESETS:</span>
          {PRESETS.map((p, idx) => (
            <button
              key={idx}
              onClick={() => setQuery(p.sql)}
              className="px-2.5 py-1 rounded-lg text-[10px] font-pixl font-semibold bg-black/40 border border-white/10 text-slate-300 hover:text-white hover:border-pink-500/40 transition"
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* Query Editor Box */}
      <div className="flex-shrink-0 rounded-xl overflow-hidden border border-slate-700/80 bg-slate-950/90 shadow-lg">
        <textarea
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={3}
          spellCheck={false}
          className="w-full p-3.5 bg-transparent border-0 resize-none font-code text-xs text-pink-300 focus:outline-none focus:ring-0 leading-relaxed"
          placeholder="Enter SQL SELECT statement..."
        />
        <div className="flex items-center justify-between px-3.5 py-2 bg-[#090514] border-t border-slate-800 text-xs font-rajdhani">
          <span className="text-slate-500 text-[11px] hidden sm:inline">
            Press <kbd className="px-1 py-0.5 rounded bg-slate-800 text-slate-300 font-code text-[10px]">Ctrl+Enter</kbd> to execute
          </span>
          <button
            onClick={() => onExecuteQuery(query)}
            disabled={isLoading || !query.trim()}
            className="ml-auto px-4 py-1.5 rounded-lg font-pixl font-bold text-xs flex items-center gap-1.5 bg-gradient-to-r from-[#ff007f] to-[#ff8c00] text-white shadow-[0_0_12px_rgba(255,0,127,0.3)] hover:shadow-[0_0_16px_rgba(255,0,127,0.5)] transition disabled:opacity-50"
          >
            <Play className="w-3 h-3 fill-current" />
            <span>{isLoading ? 'EXECUTING...' : 'EXECUTE ON D1'}</span>
          </button>
        </div>
      </div>

      {/* Error Banner */}
      {error && (
        <div className="flex-shrink-0 p-3 rounded-xl bg-red-950/40 border border-red-500/40 text-xs text-red-300 flex items-center gap-2">
          <AlertCircle className="w-4 h-4 flex-shrink-0 text-red-400" />
          <span>{error}</span>
        </div>
      )}

      {/* Results Table */}
      <div className="flex-1 flex flex-col min-h-0 rounded-xl bg-black/40 border border-white/5 overflow-hidden">
        <div className="px-3.5 py-2 bg-slate-900/60 border-b border-white/5 flex items-center justify-between text-xs font-pixl font-bold text-slate-400">
          <div className="flex items-center gap-1.5">
            <Table className="w-3.5 h-3.5 text-cyan-400" />
            <span>QUERY RESULTS ({results?.length || 0} ROWS)</span>
          </div>
        </div>

        <div className="flex-1 min-h-0 overflow-auto scrollbar-thin">
          {!results || results.length === 0 ? (
            <div className="p-8 text-center text-xs text-slate-500">
              Execute a SQL query above to view live data from Cloudflare D1 tables.
            </div>
          ) : (
            <table className="w-full text-left text-xs font-code border-collapse">
              <thead>
                <tr className="bg-slate-900/80 text-slate-400 border-b border-white/10 sticky top-0">
                  {columns.map((col, idx) => (
                    <th key={idx} className="p-2.5 font-bold uppercase tracking-wider text-[11px] whitespace-nowrap">
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {results.map((row, rIdx) => (
                  <tr key={rIdx} className="hover:bg-pink-950/20 transition">
                    {columns.map((col, cIdx) => (
                      <td key={cIdx} className="p-2.5 text-slate-300 whitespace-nowrap max-w-xs truncate">
                        {row[col] !== null && typeof row[col] === 'object' 
                          ? JSON.stringify(row[col]) 
                          : String(row[col] ?? 'null')}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

    </div>
  );
}
