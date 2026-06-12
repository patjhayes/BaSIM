from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List


@dataclass(slots=True)
class SoakwellSize:
    """Defines a standard soakwell product.

    Geometry notes (standard WA precast concrete soakwells):
    - **Base**: The base slab has a circular opening whose diameter is
      300 mm smaller than the soakwell diameter.  Only this opening area
      is pervious and contributes to base infiltration.
    - **Side walls**: Infiltration occurs through louvre slots cast into
      the concrete wall.  Each louvre is 150 mm wide × 50 mm high,
      arranged on a 300 mm × 300 mm grid.  The open-area ratio of the
      wall is therefore (0.15 × 0.05) / (0.3 × 0.3) ≈ 8.33 %.
    """

    name: str
    diameter_mm: int
    height_mm: int
    void_ratio: float
    effective_depth_mm: int | None = None
    notes: str | None = None

    # Base-opening reduction (mm smaller than outer diameter)
    _BASE_OPENING_REDUCTION_MM: int = 300

    # Louvre slot dimensions and spacing (mm)
    _LOUVRE_WIDTH_MM: int = 150
    _LOUVRE_HEIGHT_MM: int = 50
    _LOUVRE_SPACING_MM: int = 300  # centre-to-centre, both directions

    @property
    def radius_m(self) -> float:
        return (self.diameter_mm / 1000.0) / 2.0

    @property
    def effective_height_m(self) -> float:
        height = self.effective_depth_mm if self.effective_depth_mm else self.height_mm
        return height / 1000.0

    @property
    def storage_volume_m3(self) -> float:
        import math

        cylinder_volume = math.pi * self.radius_m**2 * self.effective_height_m
        return cylinder_volume * self.void_ratio

    @property
    def side_area_m2(self) -> float:
        """Effective side infiltration area through louvre openings.

        Louvres are 150 mm × 50 mm holes on a 300 mm × 300 mm grid.
        The total open area equals the full cylinder side-wall area
        multiplied by the open-area ratio of the louvre pattern.
        """
        import math

        circumference = 2 * math.pi * self.radius_m
        full_side_area = circumference * self.effective_height_m
        louvre_open_area = (
            self._LOUVRE_WIDTH_MM * self._LOUVRE_HEIGHT_MM
        ) / (self._LOUVRE_SPACING_MM ** 2)  # dimensionless ratio
        return full_side_area * louvre_open_area

    @property
    def base_area_m2(self) -> float:
        """Effective base infiltration area (the opening in the base slab).

        The base slab has a circular hole whose diameter is 300 mm less
        than the overall soakwell diameter.
        """
        import math

        opening_diameter_m = max(
            0.0,
            (self.diameter_mm - self._BASE_OPENING_REDUCTION_MM) / 1000.0,
        )
        return math.pi / 4.0 * opening_diameter_m ** 2


class SoakwellCatalogue:
    """Catalogue of soakwell sizes available for optimisation."""

    def __init__(self, sizes: Iterable[SoakwellSize]):
        self._sizes: List[SoakwellSize] = list(sizes)
        if not self._sizes:
            raise ValueError("Catalogue cannot be empty")

    def sizes(self) -> List[SoakwellSize]:
        return list(self._sizes)

    def find(self, name: str) -> SoakwellSize:
        for size in self._sizes:
            if size.name.lower() == name.lower():
                return size
        raise KeyError(f"Soakwell '{name}' not found in catalogue")


STANDARD_SOAKWELL_DIAMETERS_MM = tuple(range(300, 2401, 300))
STANDARD_SOAKWELL_DEPTHS_MM = tuple(range(300, 2401, 300))


def _build_standard_soakwell_size(diameter_mm: int, depth_mm: int) -> SoakwellSize:
    size = SoakwellSize(
        name=f"{diameter_mm} x {depth_mm}",
        diameter_mm=diameter_mm,
        height_mm=depth_mm,
        void_ratio=1.0,
    )
    size.notes = f"~{round(size.storage_volume_m3 * 1000):.0f} litres"
    return size


# Standard WA concrete soakwells — hollow cylinders (void_ratio = 1.0).
# Dimensions are internal diameter × internal depth.
# Storage volume = π/4 × d² × H  (Argue 2004; Stormwater Management Manual Ch9).
# The City of Cockburn supplier guide lists the full 300 mm matrix from
# 300 mm to 2400 mm for both diameter and depth.
DEFAULT_SOAKWELL_CATALOGUE = SoakwellCatalogue(
    _build_standard_soakwell_size(diameter_mm, depth_mm)
    for diameter_mm in STANDARD_SOAKWELL_DIAMETERS_MM
    for depth_mm in STANDARD_SOAKWELL_DEPTHS_MM
)
