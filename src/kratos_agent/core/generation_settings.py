"""Persist workspace generation preferences, constrained by advertised API capabilities."""
import json
import math
from pathlib import Path


class GenerationSettings:
    def __init__(self, workspace: Path):
        self.path = workspace / '.kratos/generation-settings.json'
        try:
            self.values = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            self.values = {}
        if not isinstance(self.values, dict):
            self.values = {}

    @staticmethod
    def capabilities(metadata):
        metadata = metadata or {}
        parameters = metadata.get('supported_parameters') or []
        if not isinstance(parameters, list):
            parameters = []
        tiers = metadata.get('effort_tiers') or []
        tiers = [tier for tier in tiers if isinstance(tier, str)] if isinstance(tiers, list) else []
        limit = metadata.get('max_output_tokens')
        limit = limit if type(limit) is int and limit >= 128 else None
        return {'temperature': metadata.get('supports_temperature') is True or 'temperature' in parameters,
                'effort_tiers': tiers, 'max_output_tokens': limit}

    def status(self, model, metadata):
        caps = self.capabilities(metadata)
        saved = self.values.get(model, {})
        if not isinstance(saved, dict):
            saved = {}
        options = {}
        temperature = saved.get('temperature')
        if caps['temperature'] and type(temperature) in (int, float) and math.isfinite(temperature) and 0 <= temperature <= 2:
            options['temperature'] = temperature
        if saved.get('reasoning_effort') in caps['effort_tiers']:
            options['reasoning_effort'] = saved['reasoning_effort']
        if caps['max_output_tokens'] and type(saved.get('max_tokens')) is int and saved['max_tokens'] >= 128:
            options['max_tokens'] = min(saved['max_tokens'], caps['max_output_tokens'])
        inspection_limit = saved.get('inspection_limit', 12)
        if type(inspection_limit) is not int or not 4 <= inspection_limit <= 50:
            inspection_limit = 12
        return {'model': model, 'capabilities': caps, 'options': options, 'inspection_limit': inspection_limit}

    def update(self, model, metadata, payload):
        if not isinstance(payload, dict) or set(payload) - {'temperature', 'reasoning_effort', 'max_tokens', 'inspection_limit'}:
            raise ValueError('Unknown generation setting')
        caps = self.capabilities(metadata)
        previous = self.values.get(model, {})
        saved = dict(previous) if isinstance(previous, dict) else {}
        for key, value in payload.items():
            if value is None:
                saved.pop(key, None)
                continue
            if key == 'temperature':
                if not caps['temperature']:
                    raise ValueError('This API does not advertise temperature control')
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 2:
                    raise ValueError('Temperature must be between 0 and 2')
            elif key == 'reasoning_effort':
                if value not in caps['effort_tiers']:
                    raise ValueError('Thinking effort is not supported by this model')
            elif key == 'max_tokens':
                if not caps['max_output_tokens'] or type(value) is not int or not 128 <= value <= caps['max_output_tokens']:
                    raise ValueError('Output limit must fit the advertised model limit')
            elif type(value) is not int or not 4 <= value <= 50:
                raise ValueError('Inspection limit must be between 4 and 50')
            saved[key] = value
        updated = dict(self.values)
        updated[model] = saved
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(updated), encoding='utf-8')
        temp.replace(self.path)
        self.values = updated
        return self.status(model, metadata)
