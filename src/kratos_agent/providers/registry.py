"""Central Provider Registry managing execution runtimes, health, and fallback chains."""
from __future__ import annotations

import inspect
import logging
import threading
import time
from typing import Any

from .antigravity.adapter import AntigravityAdapter
from .base import AgentBackend, ProviderUnavailable
from .claude.adapter import ClaudeAdapter
from .codex.adapter import CodexAdapter
from .deepseek.adapter import DeepSeekHarnessAdapter
from .health import CircuitBreaker, HealthStatus, ProviderHealth
from .kimi.adapter import KimiAdapter
from .kratos_native import KratosNativeBackend

logger = logging.getLogger(__name__)


class ProviderRegistry:
    """Thread-safe catalog of pluggable agent backends."""

    _instance: ProviderRegistry | None = None
    _singleton_lock = threading.Lock()

    def __init__(self) -> None:
        self._providers: dict[str, AgentBackend] = {}
        self._circuit_breakers: dict[str, CircuitBreaker] = {}
        self._default_provider_name: str = "kratos_native"
        self._fallback_chain: list[str] = ["codex", "claude", "kimi", "deepseek", "kratos_native"]
        self._health_cache: dict[str, tuple[float, ProviderHealth]] = {}
        self._lock = threading.RLock()

        # Register default backends lazily
        self._register_default_backends()

    @classmethod
    def get_instance(cls) -> ProviderRegistry:
        """Returns the process-wide singleton ProviderRegistry."""
        if cls._instance is None:
            with cls._singleton_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _register_default_backends(self) -> None:
        """Registers all built-in specialist adapters."""
        # 1. Native Kratos backend (always available)
        self.register_provider(KratosNativeBackend(), set_default=True)

        # 2. Codex
        self.register_provider(CodexAdapter())

        # 3. Claude
        self.register_provider(ClaudeAdapter())

        # 4. Kimi
        self.register_provider(KimiAdapter())

        # 5. DeepSeek Harness
        self.register_provider(DeepSeekHarnessAdapter())

        # 6. Antigravity (disabled by default behind feature flag)
        self.register_provider(AntigravityAdapter(enabled=False))

    def register_provider(
        self,
        backend: AgentBackend,
        set_default: bool = False,
    ) -> None:
        """Registers an AgentBackend implementation."""
        name = backend.name.lower()
        with self._lock:
            self._providers[name] = backend
            if name not in self._circuit_breakers:
                self._circuit_breakers[name] = CircuitBreaker(provider_name=name)
            if set_default:
                self._default_provider_name = name
            logger.info("Registered agent backend: %s (default=%s)", name, set_default)

    def unregister_provider(self, name: str) -> bool:
        """Unregisters an agent backend."""
        name = name.lower()
        with self._lock:
            if name in self._providers:
                del self._providers[name]
                self._circuit_breakers.pop(name, None)
                if self._default_provider_name == name:
                    self._default_provider_name = "kratos_native" if "kratos_native" in self._providers else ""
                return True
        return False

    def get(self, name: str | None = None) -> AgentBackend:
        """Retrieves backend by name or raises ProviderUnavailable."""
        with self._lock:
            target = (name or self._default_provider_name).lower()
            backend = self._providers.get(target)
            if not backend:
                raise ProviderUnavailable(provider=target, message=f"Backend '{target}' is not registered.")
            return backend

    def get_provider(self, name: str | None = None) -> AgentBackend | None:
        """Retrieves backend by name or returns None."""
        with self._lock:
            target = (name or self._default_provider_name).lower()
            return self._providers.get(target)

    def get_default_provider(self) -> AgentBackend | None:
        return self.get_provider(self._default_provider_name)

    def set_default_provider(self, name: str) -> bool:
        target = name.lower()
        with self._lock:
            if target in self._providers:
                self._default_provider_name = target
                return True
        return False

    def set_fallback_chain(self, chain: list[str]) -> None:
        with self._lock:
            self._fallback_chain = [p.lower() for p in chain if p.lower() in self._providers]

    def get_fallback_chain(self, primary_provider: str | None = None) -> list[str]:
        """Returns the fallback chain excluding the primary provider."""
        with self._lock:
            chain = list(self._fallback_chain)
            if primary_provider:
                p = primary_provider.lower()
                chain = [item for item in chain if item != p]
            return chain

    def circuit_breaker(self, provider_name: str) -> CircuitBreaker:
        return self.get_circuit_breaker(provider_name)

    def get_circuit_breaker(self, provider_name: str) -> CircuitBreaker:
        name = provider_name.lower()
        with self._lock:
            if name not in self._circuit_breakers:
                self._circuit_breakers[name] = CircuitBreaker(provider_name=name)
            return self._circuit_breakers[name]

    def list_providers(self) -> dict[str, AgentBackend]:
        """Returns dict of name -> AgentBackend."""
        with self._lock:
            return dict(self._providers)

    def health_check(self, provider_name: str) -> ProviderHealth:
        """Synchronously check health probe of provider with short TTL cache."""
        now = time.time()
        p_key = provider_name.lower()
        with self._lock:
            cached = self._health_cache.get(p_key)
            if cached and (now - cached[0] < 5.0):
                return cached[1]

        backend = self.get_provider(provider_name)
        if not backend:
            res = ProviderHealth(
                provider=provider_name,
                status=HealthStatus.OFFLINE,
                details="Provider not registered in catalog.",
            )
            with self._lock:
                self._health_cache[p_key] = (now, res)
            return res

        import asyncio
        try:
            raw_health = backend.health_check()
            if not inspect.iscoroutine(raw_health):
                if isinstance(raw_health, ProviderHealth):
                    res = raw_health
                elif isinstance(raw_health, dict):
                    st = raw_health.get("status", "ready")
                    res = ProviderHealth(
                        provider=provider_name,
                        status=HealthStatus(st) if st in HealthStatus._value2member_map_ else HealthStatus.READY,
                        details=str(raw_health.get("details", "")),
                    )
                else:
                    res = ProviderHealth(provider=provider_name, status=HealthStatus.READY)
                with self._lock:
                    self._health_cache[p_key] = (now, res)
                return res

            loop = None
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                pass

            if loop and loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    res = pool.submit(lambda: asyncio.run(raw_health)).result(timeout=1.0)
            else:
                res = asyncio.run(raw_health)

            if isinstance(res, ProviderHealth):
                health = res
            elif isinstance(res, dict):
                st = res.get("status", "ready")
                health = ProviderHealth(
                    provider=provider_name,
                    status=HealthStatus(st) if st in HealthStatus._value2member_map_ else HealthStatus.READY,
                    details=str(res.get("details", "")),
                )
            else:
                health = ProviderHealth(provider=provider_name, status=HealthStatus.READY)

            with self._lock:
                self._health_cache[p_key] = (now, health)
            return health
        except Exception as e:
            res = ProviderHealth(
                provider=provider_name,
                status=HealthStatus.OFFLINE,
                details=f"Health probe failed: {e}",
            )
            with self._lock:
                self._health_cache[p_key] = (now, res)
            return res

    async def check_all_health(self) -> dict[str, ProviderHealth]:
        """Probes health across all registered backends."""
        healths: dict[str, ProviderHealth] = {}
        with self._lock:
            backends = list(self._providers.items())

        for name, backend in backends:
            cb = self.get_circuit_breaker(name)
            try:
                ph = await backend.health_check()
                if not isinstance(ph, ProviderHealth):
                    ph = ProviderHealth(provider=name, status=HealthStatus.READY)
                if ph.is_usable:
                    cb.record_success()
                else:
                    cb.record_failure(ph.details)
            except Exception as exc:
                cb.record_failure(str(exc))
                ph = ProviderHealth(
                    provider=name,
                    status=HealthStatus.OFFLINE,
                    circuit_state=cb.state,
                    details=str(exc),
                )
            healths[name] = ph

        return healths


# Global singleton provider registry
provider_registry = ProviderRegistry.get_instance()
