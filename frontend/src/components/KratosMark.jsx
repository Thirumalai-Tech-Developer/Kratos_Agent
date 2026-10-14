import React, { useId } from 'react';

/** A geometric K, shared by the workspace and every assistant message. */
export default function KratosMark({ size = 32, className = '', title = 'Kratos' }) {
  const id = `kratos-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`;
  return <svg width={size} height={size} viewBox="0 0 40 40" fill="none" className={`kratos-mark ${className}`}
    role={title ? 'img' : undefined} aria-label={title || undefined} aria-hidden={!title || undefined}>
    {title && <title>{title}</title>}
    <defs><linearGradient id={id} x1="9" y1="7" x2="31" y2="32" gradientUnits="userSpaceOnUse">
      <stop stopColor="#C4B5FD" /><stop offset=".6" stopColor="#A78BFA" /><stop offset="1" stopColor="#67E8F9" />
    </linearGradient></defs>
    <rect x="1" y="1" width="38" height="38" rx="12" fill="#231E36" stroke="#655486" strokeOpacity=".6" />
    <path d="M10 9h5v22h-5V9Zm8 10 9-10h6L23 20l10 11h-6L18 21v-2Z" fill={`url(#${id})`} />
    <path d="m16 18 4 2-4 2v-4Z" fill="#67E8F9" />
  </svg>;
}
