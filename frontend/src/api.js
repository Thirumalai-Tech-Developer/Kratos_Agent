/** Resolve the same API in the standalone console and the bundled dashboard. */
import { getUserProfile, profileRequestPath } from './userProfile';

export function apiFetch(path, options) {
  const integrated = window.location.pathname.startsWith('/dashboard/kratos/workspace');
  return fetch(profileRequestPath(path, getUserProfile(), integrated), options);
}
