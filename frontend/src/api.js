/** Resolve the same API in the standalone console and the bundled dashboard. */
export function apiFetch(path, options) {
  const integrated = window.location.pathname.startsWith('/dashboard/kratos/workspace');
  return fetch(integrated ? path.replace(/^\/api(?=\/)/, '/api/kratos') : path, options);
}
