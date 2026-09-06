import React from 'react';
import { Flame, Sparkles } from 'lucide-react';

const SHORTCUTS = [
  {
    id: 'arch',
    label: '🏎️ Project Architecture Audit',
    prompt: "Inspect this project's architecture, tools, and recent files, then report any improvements."
  },
  {
    id: 'tools',
    label: '🗡️ Autonomous Tools Arsenal',
    prompt: "What autonomous tools do you have loaded, what permissions do they need, and what model are you using?"
  },
  {
    id: 'tests',
    label: '⚡ Test & Verification Sweep',
    prompt: "Execute unit test discovery with python -m unittest discover -s tests and verify results."
  },
  {
    id: 'd1',
    label: '🌴 Cloudflare D1 Architecture',
    prompt: "Explain how you store sessions and agentic traces in Cloudflare D1 and show an example schema."
  }
];

export default function RecruiterStrip({ onSelectPrompt }) {
  return (
    <div className="w-full bg-[#0d071a]/90 border-b border-pink-500/15 px-4 sm:px-6 lg:px-8 py-2.5">
      <div className="max-w-[1600px] mx-auto flex flex-col md:flex-row items-start md:items-center justify-between gap-2.5">
        
        {/* Label */}
        <div className="flex items-center gap-2 text-xs font-pixl font-bold text-slate-300 tracking-wider whitespace-nowrap">
          <Flame className="w-4 h-4 text-orange-500 animate-pulse" />
          <span className="text-orange-400 font-extrabold">RECRUITER DEMO SHORTCUTS:</span>
        </div>

        {/* Shortcut Pills */}
        <div className="flex items-center gap-2 overflow-x-auto w-full md:w-auto pb-1 md:pb-0 scrollbar-none">
          {SHORTCUTS.map((sc) => (
            <button
              key={sc.id}
              onClick={() => onSelectPrompt(sc.prompt)}
              className="whitespace-nowrap px-3 py-1 rounded-full text-[10.5px] font-pixl font-bold text-slate-200 bg-slate-900/80 border border-slate-700/70 hover:border-pink-500/60 hover:text-pink-300 hover:shadow-[0_0_12px_rgba(255,0,127,0.3)] transition-all duration-200"
            >
              {sc.label}
            </button>
          ))}
        </div>

      </div>
    </div>
  );
}
