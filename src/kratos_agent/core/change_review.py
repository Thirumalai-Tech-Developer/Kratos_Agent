"""Local turn checkpoints, source diffs, and conflict-checked file restoration."""
from __future__ import annotations

import difflib
import hashlib
import json
import logging
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path
from functools import wraps


def checkpoint_turn(method):
    """Capture edits even when a turn fails; capture problems must not block a turn."""
    @wraps(method)
    def wrapped(self, query, *args, **kwargs):
        pending = None
        review = getattr(self, 'change_review', None)
        if review is not None:
            try:
                session = getattr(self.memory, 'active_session', None)
                pending = review.begin(query, getattr(session, 'session_id', None))
            except Exception as exc:
                logging.getLogger(__name__).warning('Task checkpoint unavailable: %s', exc)
        try:
            return method(self, query, *args, **kwargs)
        finally:
            if pending is not None:
                try:
                    review.finish(pending)
                except Exception as exc:
                    logging.getLogger(__name__).warning('Task change review unavailable: %s', exc)
    return wrapped


class ReviewConflict(ValueError):
    pass


class ChangeReview:
    MAX_FILE = 1024 * 1024
    MAX_TOTAL = 256 * 1024 * 1024
    MAX_FILES = 25000
    EXCLUDED = {'.git', '.kratos', '.venv', 'node_modules', '__pycache__', '.next', '.build',
                'dist', 'build', '.pytest_cache', '.wrangler', 'venv'}
    SECRET_NAMES = {'accounts.json', 'creds.json', 'token.json', 'current_account.json',
                    'secrets.json', 'credentials.json', 'cookies.json', 'studio-secrets.json'}

    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()
        self.store = self.workspace / '.kratos' / 'checkpoints'
        self.lock = threading.RLock()

    def _path(self, relative: str, checked: set[Path] | None = None) -> Path:
        path = Path(relative)
        if path.is_absolute() or path.drive or path.root or '..' in path.parts or not path.parts:
            raise ValueError('Invalid workspace path')
        if any(part.lower() in self.EXCLUDED for part in path.parts):
            raise ValueError('Runtime and dependency files are excluded')
        name = path.name.lower()
        if name.startswith(('.env', '.dev.vars')) or name in self.SECRET_NAMES or name.startswith('client_secret') or path.suffix.lower() in {'.env', '.key', '.pem', '.p12', '.pfx', '.db', '.sqlite', '.sqlite3'}:
            raise ValueError('Credential and database files are excluded')
        target = self.workspace / path
        for ancestor in [target, *target.parents]:
            if ancestor == self.workspace:
                break
            if ancestor != target and checked is not None and ancestor in checked:
                break
            if ancestor.is_symlink() or (hasattr(ancestor, 'is_junction') and ancestor.is_junction()):
                raise ValueError('Linked paths are excluded')
            if ancestor != target and checked is not None:
                checked.add(ancestor)
        return target

    def _files(self) -> set[str]:
        try:
            result = subprocess.run(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard', '--', '.'],
                                    cwd=self.workspace, capture_output=True, timeout=10, check=True)
            names = result.stdout.decode('utf-8', errors='surrogateescape').split('\0')
        except (OSError, subprocess.SubprocessError):
            names = []
            for root, dirs, files in os.walk(self.workspace, followlinks=False):
                dirs[:] = [d for d in dirs if d.lower() not in self.EXCLUDED and not (Path(root) / d).is_symlink()]
                names.extend((Path(root) / name).relative_to(self.workspace).as_posix() for name in files)
        eligible = set()
        checked = set()
        for name in names:
            if name:
                try:
                    if self._path(name, checked).is_file():
                        eligible.add(Path(name).as_posix())
                        if len(eligible) > self.MAX_FILES:
                            raise RuntimeError('Workspace exceeds checkpoint file limit')
                except (ValueError, OSError):
                    continue
        return eligible

    def _read(self, name: str, checked: set[Path] | None = None) -> bytes | None:
        path = self._path(name, checked)
        if not path.exists():
            return None
        if not path.is_file() or path.stat().st_size > self.MAX_FILE:
            raise ValueError('File too large or not a regular file')
        data = path.read_bytes()
        if len(data) > self.MAX_FILE:
            raise ValueError('File too large')
        return data

    @staticmethod
    def _hash(data: bytes | None) -> str | None:
        return hashlib.sha256(data).hexdigest() if data is not None else None

    def _directory(self, checkpoint: str) -> Path:
        if len(checkpoint) != 32 or any(c not in '0123456789abcdef' for c in checkpoint):
            raise ValueError('Invalid checkpoint')
        for path in (self.workspace / '.kratos', self.store, self.store / checkpoint):
            if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
                raise ValueError('Checkpoint storage cannot use linked directories')
        return self.store / checkpoint

    def _save(self, directory: Path, manifest: dict) -> None:
        temp = directory / 'manifest.tmp'
        temp.write_text(json.dumps(manifest, ensure_ascii=True), encoding='utf-8')
        temp.replace(directory / 'manifest.json')

    def begin(self, label: str, session_id: str | None = None) -> dict:
        with self.lock:
            if self.store.exists():
                finished = sorted((item for item in self.store.iterdir() if (item / 'manifest.json').is_file()),
                                  key=lambda item: item.stat().st_mtime, reverse=True)
                for obsolete in finished[29:]:
                    if obsolete.is_symlink() or obsolete.resolve().parent != self.store.resolve():
                        continue
                    for child in obsolete.iterdir():
                        if child.is_file() and not child.is_symlink():
                            child.unlink()
                    if not any(obsolete.iterdir()):
                        obsolete.rmdir()
            names = self._files()
            checkpoint = uuid.uuid4().hex
            directory = self._directory(checkpoint)
            directory.mkdir(parents=True, exist_ok=False)
            baseline, skipped, total = {}, [], 0
            checked = set()
            for name in sorted(names):
                try:
                    data = self._read(name, checked)
                    if data is None:
                        continue
                    if total + len(data) > self.MAX_TOTAL:
                        skipped.append(name)
                        continue
                    digest = self._hash(data)
                    total += len(data)
                    baseline[name] = {'hash': digest, 'data': data, 'mode': self._path(name, checked).stat().st_mode}
                except (ValueError, OSError):
                    skipped.append(name)
            return {'id': checkpoint, 'created_at': time.time(), 'label': label[:160],
                    'session_id': session_id, 'baseline': baseline, 'known': names, 'skipped': skipped}

    def finish(self, pending: dict) -> None:
        with self.lock:
            directory = self._directory(pending['id'])
            baseline = pending['baseline']
            current = self._files()
            changes, skipped, total = [], list(pending['skipped']), 0
            checked = set()
            for name in sorted(set(baseline) | (current - pending['known'])):
                try:
                    data = self._read(name, checked)
                    digest = self._hash(data)
                    before = baseline.get(name, {}).get('hash')
                    if digest == before:
                        continue
                    if before is not None:
                        (directory / before).write_bytes(baseline[name]['data'])
                    if data is not None:
                        if total + len(data) > self.MAX_TOTAL:
                            skipped.append(name)
                            continue
                        total += len(data)
                        (directory / digest).write_bytes(data)
                    changes.append({'path': name, 'before': before, 'after': digest,
                                    'mode': baseline.get(name, {}).get('mode'), 'restored': False,
                                    'kind': 'created' if before is None else 'deleted' if digest is None else 'modified'})
                except (OSError, ValueError):
                    skipped.append(name)
            manifest = {key: pending[key] for key in ('id', 'created_at', 'label', 'session_id')}
            manifest.update(changes=changes, skipped=sorted(set(skipped)))
            self._save(directory, manifest)
            # Keep only blobs used by changed files.
            keep = {item[field] for item in changes for field in ('before', 'after') if item[field]}
            for blob in directory.iterdir():
                if len(blob.name) == 64 and blob.name not in keep:
                    blob.unlink()

    def _load(self, checkpoint: str) -> dict:
        try:
            return json.loads((self._directory(checkpoint) / 'manifest.json').read_text(encoding='utf-8'))
        except FileNotFoundError:
            raise ValueError('Checkpoint not found') from None

    def list(self) -> list[dict]:
        with self.lock:
            manifests = []
            if self.store.exists():
                for directory in self.store.iterdir():
                    try:
                        manifest = self._load(directory.name)
                        manifests.append(manifest)
                    except (ValueError, OSError):
                        continue
            return sorted(manifests, key=lambda item: item['created_at'], reverse=True)[:50]

    def diff(self, checkpoint: str, name: str) -> dict:
        with self.lock:
            manifest = self._load(checkpoint)
            change = next((item for item in manifest['changes'] if item['path'] == name), None)
            if change is None:
                raise ValueError('File is not in this checkpoint')
            directory = self._directory(checkpoint)
            before = (directory / change['before']).read_bytes() if change['before'] else b''
            after = (directory / change['after']).read_bytes() if change['after'] else b''
            try:
                if b'\0' in before or b'\0' in after:
                    raise UnicodeError
                lines = list(difflib.unified_diff(before.decode('utf-8').splitlines(), after.decode('utf-8').splitlines(),
                             fromfile=f'before/{name}', tofile=f'after/{name}', lineterm=''))
                return {'path': name, 'binary': False, 'diff': '\n'.join(lines[:6000]), 'truncated': len(lines) > 6000}
            except UnicodeError:
                return {'path': name, 'binary': True, 'diff': '', 'truncated': False}

    def restore(self, checkpoint: str, names: list[str]) -> dict:
        with self.lock:
            if not names or len(names) != len(set(names)):
                raise ValueError('Select distinct files to restore')
            manifest = self._load(checkpoint)
            by_name = {item['path']: item for item in manifest['changes']}
            selected = []
            for name in names:
                item = by_name.get(name)
                if not item or item['restored']:
                    raise ValueError('File is unavailable for restore')
                if self._hash(self._read(name)) != item['after']:
                    raise ReviewConflict(f'{name} changed after this task. Restore stopped; no files changed.')
                selected.append(item)
            directory = self._directory(checkpoint)
            for item in selected:
                target = self._path(item['path'])
                if item['before'] is None:
                    target.unlink()
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    temp = target.with_name(f'.{target.name}.kratos-{uuid.uuid4().hex}.tmp')
                    try:
                        temp.write_bytes((directory / item['before']).read_bytes())
                        if item['mode'] is not None:
                            temp.chmod(item['mode'])
                        temp.replace(target)
                    finally:
                        temp.unlink(missing_ok=True)
                item['restored'] = True
                self._save(directory, manifest)
            return {'restored': names}
