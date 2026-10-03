"""Bound repetitive model output and repeated inspections without inventing edits."""
import hashlib
import json
import re


class RepetitiveOutputError(RuntimeError):
    pass


def repetitive_output(text: str) -> bool:
    # Ignore small repeats, whitespace/ASCII art, and widely separated phrases.
    sample = text[-8192:]
    for match in re.finditer(r'(.{3,160}?)\1{11,}', sample, re.DOTALL):
        if len(match.group()) >= 256 and re.search(r'[A-Za-z0-9]', match.group(1)):
            return True
    return False


class OutputGuard:
    def __init__(self):
        self.tail = ''
        self.since_check = 0

    def push(self, chunk: str):
        self.tail = (self.tail + chunk)[-8192:]
        self.since_check += len(chunk)
        if self.since_check >= 64:
            self.since_check = 0
            if repetitive_output(self.tail):
                raise RepetitiveOutputError('Repeated output detected; generation was stopped.')


class ProgressGuard:
    READ_TOOLS = {'read_file', 'list_directory', 'grep_search', 'search_symbol', 'read_symbol',
                  'view_outline', 'inspect_page_dom', 'fetch_web_page', 'fetch_url', 'search_web', 'google_search',
                  'browser_read', 'browser_snapshot_dom', 'computer_browser_read'}
    EDIT_TOOLS = {'write_file', 'edit_file', 'replace_file_content', 'multi_replace_file_content'}

    def __init__(self, query: str, inspection_limit: int = 12):
        self.inspection_limit = inspection_limit
        self.needs_edit = bool(re.search(r'\b(?:fix|edit|change|implement|build|create|write|update|add|remove|refactor)\b', query, re.I))
        self.reads = 0
        self.fingerprints = {}
        self.blocked = 0

    def observe(self, call, result) -> str | None:
        command = str(call.arguments.get('command') or call.arguments.get('argv') or '')
        terminal_edit = call.name == 'run_terminal_command' and bool(re.search(
            r'\b(?:Set-Content|Out-File|Add-Content|Copy-Item|Move-Item|Remove-Item|New-Item|mkdir|mv|cp|rm)\b', command, re.I))
        if (call.name in self.EDIT_TOOLS or terminal_edit) and not result.is_error:
            self.reads = 0
            self.fingerprints.clear()
            self.blocked = 0
            return None
        if not self.is_inspection(call):
            return None
        if result.is_error and result.content.startswith('Unchanged inspection blocked.'):
            self.blocked += 1
            return 'Progress guard: stop repeating this inspection. Perform the requested edit or report the blocker.'
        self.reads += 1
        key = (call.name, json.dumps(call.arguments, sort_keys=True, default=str))
        digest = hashlib.sha256(result.content.encode('utf-8')).hexdigest()
        previous, count = self.fingerprints.get(key, (None, 0))
        count = count + 1 if digest == previous else 1
        self.fingerprints[key] = (digest, count)
        if count >= 3 or (self.needs_edit and self.reads >= self.inspection_limit):
            self.blocked += 1
            return ('Progress guard: inspection is repeating without an edit. Use the evidence already collected '
                    'to make the requested edit, inspect a genuinely different unresolved issue, or report the '
                    'specific blocker. Do not repeat unchanged reads or claim the edit is done.')
        return None

    def repeated(self, call) -> bool:
        key = (call.name, json.dumps(call.arguments, sort_keys=True, default=str))
        return self.is_inspection(call) and self.fingerprints.get(key, (None, 0))[1] >= 3

    def is_inspection(self, call) -> bool:
        if call.name in self.READ_TOOLS:
            return True
        if call.name == 'run_terminal_command':
            command = str(call.arguments.get('command') or call.arguments.get('argv') or '').lower()
            if re.search(r'copy-item|remove-item|set-content|new-item|write_file|edit_file|\b(?:mkdir|move|del|rm|cp|mv)\b', command):
                return False
            return bool(re.search(r'get-content|get-childitem|git (?:diff|status)|\brg\b|\bls\b|\bcat\b|\bdir\b', command))
        return False
