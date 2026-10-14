import React, { useEffect } from 'react';
import { RECOVERY_NOTICE_MS } from '../chatRecovery';

export default function RecoveryNotice({ notice, onDismiss }) {
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => onDismiss(null), RECOVERY_NOTICE_MS);
    return () => clearTimeout(timer);
  }, [notice, onDismiss]);

  if (!notice) return null;
  return <p className="recovery-notice" role="status" aria-live="polite">
    <span className="recovery-notice-dot" aria-hidden="true" />
    Recovering… trying another method
  </p>;
}
