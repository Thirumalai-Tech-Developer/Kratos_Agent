from .discovery import discover_capabilities
from .registry import CapabilityRegistry, get_capability_registry
from .schema import CapabilitySpec

__all__ = ["CapabilityRegistry", "CapabilitySpec", "discover_capabilities", "get_capability_registry"]
