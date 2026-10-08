# Kratos Studio on Ubuntu with Docker

This deploys the merged Kratos runtime, workspace UI, and OmniRoute gateway
together in one container. The Ubuntu host only needs Docker Engine and Compose.
Python, Node.js, Chromium, and the virtual display live inside the image.

## Single-file server installation

The packaged `kratos-docker-install.sh` contains the tracked source snapshot and
the deployment files. It does not require GitHub authentication. No local `.env`,
browser cookies, virtual environments, or untracked projects are included.

In Windows PowerShell:

```powershell
scp -P 2222 "C:\Users\thiru\Downloads\kratos-docker-install.sh" root@160.250.204.20:/root/
ssh -t -p 2222 root@160.250.204.20 "bash /root/kratos-docker-install.sh"
```

Or after uploading, run this at the Ubuntu root prompt:

```bash
bash /root/kratos-docker-install.sh
```

The installer uses [Docker's official Ubuntu repository](https://docs.docker.com/engine/install/ubuntu/),
checks the bundled archive's SHA-256, builds the image, and waits for gateway
and authenticated agent health checks. It prepares swap on small VPSs because
building the gateway needs several GB of memory. The first build downloads
dependencies and browsers; subsequent starts use the existing image.

An existing direct `kratos.service` is stopped after the image builds, then
disabled and its local unit archived after Docker becomes healthy. Its existing
workspace and gateway secrets are reused. Source files and installed host
packages from a previous installation are retained.

## Access

Studio's existing server routes require loopback access. This deployment uses
[Linux host networking](https://docs.docker.com/engine/network/drivers/host/),
with the gateway on `127.0.0.1:21128` and the private agent on `127.0.0.1:7860`.
Keep this tunnel open in a separate Windows PowerShell window:

```powershell
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -p 2222 -L 21128:127.0.0.1:21128 root@160.250.204.20
```

Open http://127.0.0.1:21128/dashboard/kratos. The installer prints the initial
dashboard password. Connect provider accounts under Providers: browser sessions
and API credentials from your Windows computer are not part of the source bundle.
If you already changed the existing dashboard password, use that current password.

The workspace includes the [AI and ML Jobs workflow](../../docs/JOBS.md).
Open **Jobs**, save your applicant profile and resume, then start auto-apply.
Chromium is installed in the image; the application ledger, resume and receipts
persist in the workspace bind mount across container updates.

Desktop actions target the container's virtual Linux display. Windows desktop
control, local microphone input, and automatic capture from your PC's browser
are disabled in the server defaults.

## Manage

```bash
cd /opt/kratos-docker
docker compose ps
docker compose logs -f --tail 100
docker compose restart kratos
docker compose stop
docker compose up -d --wait
```

`healthy` confirms both services respond. Inspect managed child-process logs
under `/var/lib/kratos/workspace/.kratos/studio/logs/` as well as Docker logs.

Settings are in `/opt/kratos-docker/.env`. After editing them, apply changes with
`docker compose up -d --force-recreate --wait`. `restart` alone does not reload
environment settings. Changing the gateway port also requires rebuilding the
image and changing the matching SSH tunnel port.

The container runs as UID/GID 10001. Persistent bind mounts:

| Host | Container | Contents |
| --- | --- | --- |
| `/var/lib/kratos/workspace` | `/workspace` | Projects, sessions, settings, encrypted gateway database, logs |
| `/var/lib/kratos/docker-home` | `/home/kratos` | User settings, browser profiles and tool caches |

Back up those two directories and `.env` with the container stopped. Rebuilding,
recreating, or removing the container retains this data.

## Build from the merged repository

On Ubuntu, run `bash deploy/docker/install.sh` as root from a checkout that
contains these deployment files. To use Compose directly:

```bash
cp deploy/docker/.env.example .env
# Set INITIAL_PASSWORD in .env before starting.
mkdir -p data/workspace data/home
sudo chown -R 10001:10001 data/workspace data/home
docker compose up -d --build --wait --wait-timeout 900
```

The Docker image installs locked Python/npm dependencies and both pinned
Playwright browser versions. It builds the frontend and the gateway with one
Next.js worker and webpack to limit memory usage.

## Package and update

Run `python deploy/docker/pack.py --output <absolute-path>.sh` in the merged
checkout. Packaging uses `git archive HEAD` plus the reviewed Docker deployment
files. It never copies ignored secrets or arbitrary untracked files. Review and
commit other source changes before packaging them.

For an update, back up the persistent directories and `.env`, then upload and
run the new packaged installer with the same commands. A managed previous source
snapshot is retained under `/opt/kratos-docker/backups/app.<timestamp>-<pid>`.
The configuration and persistent data locations stay the same. The running
container stays up during the image build, then Compose recreates it.
Unrecognized app directories are left untouched and require moving aside.

If an update fails before recreation, the previous container remains running.
For rollback after recreation, stop Compose, retain the failed app directory,
restore the previous source backup as `/opt/kratos-docker/app`, and run
`docker compose up -d --build --wait --wait-timeout 900`. Keep `.env` and the
persistent workspace in place.
