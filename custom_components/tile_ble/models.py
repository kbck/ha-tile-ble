"""Typed runtime data owned by each Tile config entry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeAlias

from homeassistant.config_entries import ConfigEntry

if TYPE_CHECKING:
    from .coordinator import TileCoordinator, TileState


@dataclass
class TileRuntimeData:
    """Reference the shared resolver and this entry's Tile state."""

    coordinator: TileCoordinator
    state: TileState


TileConfigEntry: TypeAlias = ConfigEntry[TileRuntimeData]
