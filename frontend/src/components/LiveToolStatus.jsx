import React from 'react';
import { LoaderCircle } from 'lucide-react';

export default function LiveToolStatus({ tools = [] }) {
  if (!tools.length) return null;
  return <div className="live-tool-status" role="status" aria-live="polite" aria-label="Running tools">
    <LoaderCircle size={15} className="animate-spin" /><strong>{tools.length} {tools.length === 1 ? 'tool is' : 'tools are'} running</strong>
    <span>Progress appears in the conversation.</span>
  </div>;
}
