import React, { useEffect, useRef, useState } from 'react';
import { Briefcase, Play, Square, RefreshCw, ExternalLink, Upload, CheckCircle2, AlertCircle } from 'lucide-react';
import { apiFetch } from '../api';
import './JobsWorkspace.css';

const split = value => String(value || '').split(/[\n,]/).map(item => item.trim()).filter(Boolean);
const attention = ['needs_input', 'needs_login', 'blocked', 'failed', 'uncertain', 'unsupported'];
const retryable = ['discovered', 'needs_input', 'needs_login', 'blocked', 'failed', 'stopped'];
const emptyProfile = { name: '', email: '', phone: '', city: '', country: '', skills: [], summary: '', years_experience: null, answers: {} };

function Evidence({ jobId }) {
  const [src, setSrc] = useState('');
  useEffect(() => {
    let disposed = false;
    let objectUrl;
    apiFetch(`/api/jobs/evidence?job_id=${encodeURIComponent(jobId)}`).then(async response => {
      if (!response.ok) return;
      objectUrl = URL.createObjectURL(await response.blob());
      if (!disposed) setSrc(objectUrl);
      else URL.revokeObjectURL(objectUrl);
    }).catch(() => {});
    return () => { disposed = true; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [jobId]);
  return src ? <img className="jobs-evidence" src={src} alt="Application form or employer confirmation" /> : null;
}

export default function JobsWorkspace() {
  const [data, setData] = useState(null);
  const [profile, setProfile] = useState(emptyProfile);
  const [preferences, setPreferences] = useState({});
  const [skills, setSkills] = useState('');
  const [answers, setAnswers] = useState('{}');
  const [boards, setBoards] = useState({});
  const [upload, setUpload] = useState(null);
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  const [editing, setEditing] = useState(false);
  const [filter, setFilter] = useState('all');
  const [query, setQuery] = useState('');
  const [evidence, setEvidence] = useState(null);
  const initialized = useRef(false);

  const load = async () => {
    try {
      const response = await apiFetch('/api/jobs');
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Could not load the job workspace');
      setData(result);
      if (!initialized.current) {
        initialized.current = true;
        setProfile({ ...emptyProfile, ...result.profile });
        setPreferences(result.preferences);
        setSkills((result.profile.skills || []).join(', '));
        setAnswers(JSON.stringify(result.profile.answers || {}, null, 2));
        setBoards(Object.fromEntries(Object.entries(result.preferences.boards).map(([key, values]) => [key, values.join(', ')])));
      }
    } catch (exception) { setError(exception.message); }
  };
  useEffect(() => {
    const initial = setTimeout(load, 0);
    return () => clearTimeout(initial);
  }, []);
  useEffect(() => {
    const interval = setInterval(load, data?.busy ? 2000 : 15000);
    return () => clearInterval(interval);
  }, [data?.busy]);

  const command = async (action, jobId = '', note = '') => {
    setPending(true);
    setError('');
    try {
      const response = await apiFetch('/api/jobs/control', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action, job_id: jobId, note }) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Job action failed');
      setData(result);
    } catch (exception) { setError(exception.message); }
    finally { setPending(false); }
  };

  const save = async event => {
    event.preventDefault();
    setPending(true);
    setError('');
    try {
      const payload = { profile: { ...profile, skills: split(skills), answers: JSON.parse(answers), ...(upload ? { resume: upload } : {}) },
        preferences: { ...preferences, boards: Object.fromEntries(Object.entries(boards).map(([key, value]) => [key, split(value)])) } };
      const response = await apiFetch('/api/jobs/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Could not save your applicant profile');
      setData(result);
      setProfile({ ...emptyProfile, ...result.profile });
      setPreferences(result.preferences);
      setUpload(null);
      setEditing(false);
    } catch (exception) { setError(exception.message); }
    finally { setPending(false); }
  };

  const chooseResume = event => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (file.size > 10000000) { setError('Choose a resume under 10 MB'); return; }
    const reader = new FileReader();
    reader.onload = () => setUpload({ name: file.name, data: String(reader.result).split(',')[1] });
    reader.onerror = () => setError('Could not read the resume');
    reader.readAsDataURL(file);
  };

  if (!data) return <section className="jobs-workspace"><p role="status">{error || 'Loading job workspace…'}</p></section>;
  const counts = data.counts || {};
  const matches = counts.matches ?? data.jobs.filter(job => job.eligible && job.score >= data.preferences.min_score).length;
  const shown = data.jobs.filter(job => (!query || `${job.title} ${job.company} ${job.location}`.toLowerCase().includes(query.toLowerCase())) &&
    (filter === 'all' || (filter === 'ready' && job.eligible && job.auto_apply_supported && retryable.includes(job.status)) ||
      (filter === 'attention' && attention.includes(job.status)) || job.status === filter));
  const disabled = pending || data.busy;
  const profileField = (key, label, type = 'text') => <label key={key}>{label}<input type={type} value={profile[key] || ''} onChange={event => setProfile(previous => ({ ...previous, [key]: event.target.value }))} /></label>;

  return <section className="jobs-workspace">
    <header className="jobs-header">
      <div><span className="jobs-eyebrow"><Briefcase size={15} /> CAREER WORKSPACE</span><h1>Find your next AI role.</h1><p>Discover openings, match your skills, and apply with your saved profile.</p></div>
      <div className="jobs-actions">
        <button onClick={() => setEditing(value => !value)} disabled={disabled}>Applicant profile</button>
        <button onClick={() => command('scan')} disabled={disabled}><RefreshCw size={15} /> Scan sources</button>
        {data.preferences.enabled || data.busy ? <button className="jobs-stop" onClick={() => command('stop')} disabled={pending || data.stopping}><Square size={14} /> {data.stopping ? 'Stopping…' : 'Stop auto-apply'}</button> :
          <button className="jobs-primary" onClick={() => command('start')} disabled={disabled || editing || data.missing_profile.length > 0}><Play size={14} /> Start auto-apply</button>}
      </div>
    </header>
    {error && <p role="alert" className="jobs-alert"><AlertCircle size={16} /> {error}</p>}
    {data.missing_profile.length > 0 && <div className="jobs-onboarding"><Upload size={19} /><div><strong>Add your resume and applicant details</strong><p>Required for applications: {data.missing_profile.join(', ')}. Discovery works before setup.</p></div><button onClick={() => setEditing(true)} disabled={disabled}>Set up profile</button></div>}
    <div className="jobs-metrics">
      {[['Roles collected', counts.total ?? data.jobs.length], ['Profile matches', matches], ['Submitted', counts.submitted || 0], ['Today’s attempts', `${counts.attempts_today || 0}/${data.preferences.daily_limit}`]].map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong></div>)}
    </div>
    <div className="jobs-run-status" role="status"><span className={data.preferences.enabled ? 'jobs-live' : 'jobs-paused'} />{data.activity}<small>{data.last_scan ? `Last scan ${new Date(data.last_scan).toLocaleString()}` : 'No scan yet'}</small></div>

    {editing && <form className="jobs-profile" onSubmit={save}>
      <div className="jobs-section-title"><h2>Applicant profile</h2><p>Every application uses these facts. Unknown screening answers stay unfilled.</p></div>
      <div className="jobs-form-grid">
        {profileField('name', 'Full name')}{profileField('email', 'Email', 'email')}{profileField('phone', 'Phone')}
        {profileField('city', 'City')}{profileField('country', 'Country')}{profileField('current_company', 'Current company (optional)')}
        {profileField('linkedin', 'LinkedIn URL', 'url')}{profileField('github', 'GitHub URL', 'url')}{profileField('portfolio', 'Portfolio URL', 'url')}
        <label>Skills (comma separated)<input value={skills} onChange={event => setSkills(event.target.value)} placeholder="Python, PyTorch, NLP, LLMs…" /></label>
        <label>Years of experience (optional)<input type="number" min="0" max="60" step="0.5" value={profile.years_experience ?? ''} onChange={event => setProfile(previous => ({ ...previous, years_experience: event.target.value === '' ? null : Number(event.target.value) }))} /></label>
        <label>Resume · PDF, DOCX or TXT<input type="file" accept=".pdf,.docx,.txt" onChange={chooseResume} /><small>{upload?.name || profile.resume_name || 'No resume uploaded'}</small></label>
      </div>
      <label>Experience summary<textarea rows="3" value={profile.summary || ''} onChange={event => setProfile(previous => ({ ...previous, summary: event.target.value }))} placeholder="Your actual experience and projects. Used in cover letters." /></label>
      <h3>Application preferences</h3>
      <div className="jobs-form-grid">
        <label>Daily application limit<input type="number" min="1" max="50" value={preferences.daily_limit} onChange={event => setPreferences(previous => ({ ...previous, daily_limit: Number(event.target.value) }))} /></label>
        <label>Minimum match score<input type="number" min="0" max="100" value={preferences.min_score} onChange={event => setPreferences(previous => ({ ...previous, min_score: Number(event.target.value) }))} /></label>
        <label>Scan interval (minutes)<input type="number" min="30" max="10080" value={preferences.interval_minutes} onChange={event => setPreferences(previous => ({ ...previous, interval_minutes: Number(event.target.value) }))} /></label>
        <label>Preferred locations<input value={(preferences.locations || []).join(', ')} onChange={event => setPreferences(previous => ({ ...previous, locations: event.target.value.split(',') }))} placeholder="Dubai, London, Remote…" /></label>
        <label>Role keywords<input value={(preferences.keywords || []).join(', ')} onChange={event => setPreferences(previous => ({ ...previous, keywords: event.target.value.split(',') }))} placeholder="LLM, MLOps, computer vision…" /></label>
        <label>Exclude companies<input value={(preferences.exclude_companies || []).join(', ')} onChange={event => setPreferences(previous => ({ ...previous, exclude_companies: event.target.value.split(',') }))} /></label>
      </div>
      <label className="jobs-checkbox"><input type="checkbox" checked={preferences.remote_only || false} onChange={event => setPreferences(previous => ({ ...previous, remote_only: event.target.checked }))} /> Only roles marked remote · regional restrictions still apply</label>
      <details><summary>Sources and saved screening answers</summary>
        <div className="jobs-source-options">{['remoteok', 'arbeitnow', 'greenhouse', 'lever', 'ashby'].map(source => <label className="jobs-checkbox" key={source}><input type="checkbox" checked={preferences.sources?.includes(source) || false} onChange={event => setPreferences(previous => ({ ...previous, sources: event.target.checked ? [...previous.sources, source] : previous.sources.filter(value => value !== source) }))} />{source}</label>)}</div>
        <div className="jobs-form-grid">{['greenhouse', 'lever', 'ashby'].map(source => <label key={source}>{source} employer boards<input value={boards[source] || ''} onChange={event => setBoards(previous => ({ ...previous, [source]: event.target.value }))} placeholder="Employer board names, separated by commas" /></label>)}</div>
        <label>Screening answers (exact question → your answer, JSON)<textarea className="jobs-json" rows="5" value={answers} onChange={event => setAnswers(event.target.value)} placeholder={'{"Will you require visa sponsorship?": "Yes"}'} /></label>
        <p className="jobs-hint">Use your own answers for work authorization, sponsorship, consent and screening questions. Required questions found by the worker appear in the job details.</p>
      </details>
      <div className="jobs-save"><p>Start auto-apply authorizes sending this resume, contact details and saved answers to matching employers. Stop pauses new submissions.</p><button className="jobs-primary" disabled={disabled} type="submit">{pending ? 'Saving…' : 'Save profile & preferences'}</button></div>
    </form>}

    <div className="jobs-toolbar"><div>{[['all', 'All roles'], ['ready', 'Ready to apply'], ['submitted', 'Submitted'], ['attention', 'Needs attention']].map(([value, label]) => <button key={value} aria-pressed={filter === value} onClick={() => setFilter(value)}>{label}</button>)}</div><input aria-label="Search jobs" placeholder="Search role, company or location" value={query} onChange={event => setQuery(event.target.value)} /></div>
    <div className="jobs-list">
      {!shown.length && <div className="jobs-empty"><Briefcase size={36} /><h2>{data.last_scan ? 'No roles match this view' : 'Your job search starts here'}</h2><p>{data.last_scan ? 'Try another filter or edit your source boards and location preferences.' : 'Scan the free feeds and employer boards to find current AI and ML openings.'}</p></div>}
      {shown.map(job => <article className="jobs-card" key={job.id}>
        <div className="jobs-card-top"><div><a href={job.url} target="_blank" rel="noopener noreferrer"><h2>{job.title}</h2></a><p>{job.company} · {job.location || 'Location not supplied'} {job.remote && !/remote/i.test(job.location || '') && ' · Remote'}</p></div><span className="jobs-score">{job.score}/100 match</span></div>
        <div className="jobs-tags"><a href={job.source_home} target="_blank" rel="noopener noreferrer">{job.source}</a><span className={`jobs-state jobs-state-${job.status}`}>{job.status.replaceAll('_', ' ')}</span>{job.matched_skills?.slice(0, 5).map(skill => <span key={skill}>{skill}</span>)}{!job.auto_apply_supported && <span>Manual application</span>}</div>
        {(job.detail || job.match_reasons?.length > 0) && <p className="jobs-detail">{job.detail || job.match_reasons.join(' · ')}</p>}
        <div className="jobs-card-actions"><a href={job.apply_url} target="_blank" rel="noopener noreferrer">Open application <ExternalLink size={12} /></a>
          {job.auto_apply_supported && retryable.includes(job.status) && <button disabled={disabled || data.missing_profile.length > 0 || !job.eligible} onClick={() => command('apply', job.id)}>{job.status === 'discovered' ? 'Apply automatically' : 'Retry after fixing blocker'}</button>}
          {['discovered', 'queued', 'needs_input', 'failed', 'stopped'].includes(job.status) && <button disabled={disabled} onClick={() => command('skip', job.id)}>Skip</button>}
        </div>
        <details><summary>Job details & application evidence</summary><p className="jobs-description">{job.description}</p>
          {job.receipt?.questions?.length > 0 && <div><h3>Required answers</h3><ul>{job.receipt.questions.map(question => <li key={question}>{question}</li>)}</ul></div>}
          {job.receipt?.confirmation && <p><CheckCircle2 size={14} /> {job.receipt.confirmation} · {new Date(job.receipt.confirmed_at).toLocaleString()}</p>}
          {job.receipt?.screenshot && <button onClick={() => setEvidence(evidence === job.id ? null : job.id)}>{evidence === job.id ? 'Hide screenshot' : 'Show saved screenshot'}</button>}
          {evidence === job.id && <Evidence jobId={job.id} />}
          {job.status === 'uncertain' && <form onSubmit={event => { event.preventDefault(); command('confirm_submitted', job.id, new FormData(event.currentTarget).get('confirmation')); }}><label>Employer confirmation received outside Kratos<input name="confirmation" required placeholder="Paste the employer’s confirmation or receipt reference" /></label><button disabled={pending}>Record verified submission</button></form>}
        </details>
      </article>)}
    </div>
    {counts.total > data.jobs.length && <p className="jobs-hint">Showing the highest ranked {data.jobs.length} of {counts.total} tracked roles. The worker checks queued and new matches separately.</p>}
    <details className="jobs-source-health"><summary>Source status · {data.source_reports.filter(source => source.status === 'ok').length} feeds responding</summary>{data.source_reports.map(report => <p key={`${report.source}-${report.board}`}>{report.source}{report.board && ` / ${report.board}`} — {report.status === 'ok' ? `${report.count} AI/ML roles` : report.error}</p>)}</details>
  </section>;
}
