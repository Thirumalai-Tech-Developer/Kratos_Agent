from .schema import CapabilitySpec
from .registry import CapabilityRegistry, get_capability_registry
from .discovery import discover_capabilities

__all__ = ["CapabilitySpec", "CapabilityRegistry", "get_capability_registry", "discover_capabilities"]
