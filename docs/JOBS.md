# AI and ML job applications

Kratos includes a **Jobs** tab and four agent tools. No separate MCP server,
paid job-search API, or model subscription is required for this workflow.
Job discovery and form filling run independently of the chat model.

## Start

1. Open the Kratos workspace and choose **Jobs**.
2. Open **Applicant profile**. Add your name, email, skills and a PDF, DOCX or
   TXT resume (up to 10 MB). Add your actual experience and optional contact links.
3. Choose locations, role keywords, excluded companies and a minimum match score.
   Employer board names can be edited under **Sources and saved screening answers**.
4. Save, then choose **Scan sources** to inspect matches, or **Start auto-apply**
   to scan and submit matching applications automatically.
5. **Stop auto-apply** disables the recurring worker and clears every waiting
   application. An operation already contacting an employer may need to finish
   its current browser/network step before it stops.

Starting authorizes sending your saved resume, contact details and answers to
matching employers. Applications use your supplied facts. Kratos does not make
up qualifications, work authorization, visa answers or consent.

Defaults: **5 attempts per UTC day**, a **70/100 minimum score**, and a scan every
**6 hours**. These can be adjusted in the profile editor. Failed and uncertain
attempts count toward the daily limit. The worker resumes after a normal service
restart when auto-apply was enabled; use Stop to keep it disabled.

## Free sources

| Source | Discovery | Automatic application |
| --- | --- | --- |
| Remote OK | Public remote-job feed | When its application link points to a supported ATS |
| Arbeitnow | Public job-board feed | Original listing link; other application hosts require manual completion |
| Greenhouse | Public feeds for configured employer boards | Supported hosted Greenhouse forms |
| Lever | Public feeds for configured employer boards | Supported hosted Lever forms |
| Ashby | Public feeds for configured employer boards | Supported hosted Ashby forms |

The sources cover available public openings, rather than every job on the
internet. AI/ML titles and relevant engineering/research descriptions are
filtered, then ranked using your supplied skills. Experience and location
filters can exclude roles; a remote tag alone does not establish regional
eligibility. The score is a matching heuristic, not a hiring probability.

Cards retain source attribution and links to the original job/application.
Each feed has its own status. A failing feed does not discard successful ones;
if every feed fails, discovery is retried in 30 minutes while auto-apply is on.

## Forms and screening questions

The worker uses a dedicated headless Chromium profile. Supported hosts are
`jobs.lever.co`, `jobs.eu.lever.co`, `boards.greenhouse.io`,
`job-boards.greenhouse.io`, and `jobs.ashbyhq.com`.
It fills known applicant fields, attaches the resume, and can supply a factual
cover letter from your experience summary and matching skills.

Unknown required questions are recorded as **needs input** with a screenshot.
Save exact question/answer pairs in **Screening answers** and retry that job:

```json
{
  "Will you require visa sponsorship?": "Yes",
  "I consent to the processing of my application data": true
}
```

Use the exact visible question and your own answer. Boolean answers are used
for checkboxes. Passwords, account creation, CAPTCHA/human verification,
unsupported forms and employers requiring login are left for manual completion.
Blocked applications are not automatically retried.

## Receipts and duplicate prevention

Applications are tracked in SQLite and deduplicated by job identity and
application URL, including common job identifier query parameters. A rescan
does not reset a submitted job. An atomic claim prevents two workers from
claiming the same queued record.

**Submitted** requires a new visible employer confirmation. A timeout or crash
after a submission starts is **uncertain** and cannot be automatically retried.
Verify the employer's receipt before recording its confirmation in the job
details. Screenshots and required questions can be expanded on each card.

The UI shows the highest ranked 500 records; global metrics include all tracked
roles. The worker queries queued and newly discovered jobs separately, so older
submitted roles do not hide waiting applications from the worker.

## Agent tools and API

| Tool | Action |
| --- | --- |
| `jobs_status` | View setup, matches, source status and submission counts |
| `jobs_scan` | Start a public-feed discovery scan |
| `jobs_apply` | Queue a specific matching job ID |
| `jobs_autopilot` | Start or stop recurring auto-apply |

The agent API exposes `GET /api/jobs`, `POST /api/jobs/config`,
`POST /api/jobs/control`, and authenticated `GET /api/jobs/evidence?job_id=...`.
Studio's existing gateway proxy forwards these as `/api/kratos/jobs/...`.
All use the existing internal token/dashboard authentication.

## Storage and deployment

Data stays under the selected workspace's `.kratos/jobs/`: `jobs.sqlite3`,
`documents/`, `letters/`, `evidence/`, and the dedicated `browser/` profile.
Do not put this folder into Git or a source archive. Back it up privately.

On Windows, from the merged checkout:

```powershell
uv run --no-sync kratos-studio run --workspace .
```

The normal Studio setup builds the frontend; `python -m playwright install
chromium` installs the application worker's browser if it is missing. The
[Docker deployment](../deploy/docker/README.md) includes Chromium and persists
this data at `/var/lib/kratos/workspace/.kratos/jobs/` on the server.

## Source documentation

- [Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html)
- [Lever Postings API](https://github.com/lever/postings-api)
- [Ashby public Job Postings API](https://developers.ashbyhq.com/docs/public-job-posting-api)
- [Arbeitnow API](https://www.arbeitnow.com/blog/job-board-api)
- [Arbeitnow attribution terms](https://www.arbeitnow.com/terms)
- [Remote OK public feeds](https://remoteok.featurebase.app/help/articles/3140840-is-there-an-api-or-rssjson-feed-of-remote-jobs)

Public discovery APIs do not grant employer API credentials for submissions.
The application worker uses the employer's hosted form. Automated fixture tests
verify submission handling without contacting real employers. Live feed
validation depends on outbound network access from the machine running Kratos.
