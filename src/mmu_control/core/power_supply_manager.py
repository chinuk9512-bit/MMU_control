"""Power supply control abstraction."""

from __future__ import annotations

from mmu_control.models.settings import PowerSupplySettings


class PowerSupplyManager:
    """Placeholder manager for future power supply integrations."""

    def __init__(self, settings: PowerSupplySettings | None = None) -> None:
        self.settings = settings or PowerSupplySettings()

    def update_settings(self, settings: PowerSupplySettings) -> None:
        """Store the settings that future control methods will use."""
        self.settings = settings

    def is_configured(self) -> bool:
        """Return whether a target power supply host has been configured."""
        return bool(self.settings.ip_address.strip())
