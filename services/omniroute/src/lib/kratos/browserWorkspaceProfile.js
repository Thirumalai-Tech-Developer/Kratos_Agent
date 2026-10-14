/** One browser workspace identity for the console and its management pages. */
export const USER_PROFILE_STORAGE_KEY = 'kratos-workspace-profile';
const validProfile = value => typeof value === 'string' && /^[a-f0-9]{32}$/.test(value);

export function createUserProfileResolver(environment = () => globalThis) {
  let remembered;
  return function resolveUserProfile() {
    const host = environment();
    const search = host.window?.location?.search ?? host.location?.search ?? '';
    const selected = new URLSearchParams(search).get('profile');
    let storage;
    try { storage = host.localStorage; } catch { storage = null; }
    const save = value => { try { storage?.setItem(USER_PROFILE_STORAGE_KEY, value); } catch { /* Keep the in-memory identity. */ } };
    if (validProfile(selected)) {
      remembered = selected;
      save(selected);
      return selected;
    }
    if (remembered) return remembered;
    try {
      const saved = storage?.getItem(USER_PROFILE_STORAGE_KEY);
      if (validProfile(saved)) return (remembered = saved);
    } catch { /* Restricted browser storage must not select the primary workspace. */ }
    remembered = [...host.crypto.getRandomValues(new Uint8Array(16))].map(byte => byte.toString(16).padStart(2, '0')).join('');
    save(remembered);
    return remembered;
  };
}

export const getUserProfile = createUserProfileResolver();

export function profileRequestPath(path, profile, integrated = false) {
  const target = integrated && !path.startsWith('/api/kratos/') ? path.replace(/^\/api(?=\/)/, '/api/kratos') : path;
  if (!/^\/api(?:\/|$)/.test(path)) return target;
  if (!validProfile(profile)) throw new Error('Invalid browser workspace profile');
  const hashIndex = target.indexOf('#');
  const request = hashIndex < 0 ? target : target.slice(0, hashIndex);
  const fragment = hashIndex < 0 ? '' : target.slice(hashIndex);
  const queryIndex = request.indexOf('?');
  const pathname = queryIndex < 0 ? request : request.slice(0, queryIndex);
  const query = new URLSearchParams(queryIndex < 0 ? '' : request.slice(queryIndex + 1));
  query.set('profile', profile);
  return pathname + '?' + query.toString() + fragment;
}
