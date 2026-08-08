"""Soil moisture retention parameters for basin infiltration modelling.

Provides the Van Genuchten (1980) soil moisture retention curve and the
Carsel & Parrish (1988) USDA soil-texture catalogue. These parameters
feed the Green-Ampt-Hantush 3D basin engine (see ``gah_3d_engine.py``)
which is the sole routing model used by SoakSIM.

Key physics:
- Van Genuchten (1980) soil moisture retention curve, tabulated per USDA
  texture class (Carsel & Parrish, 1988).
- Specific yield (drainable porosity) per texture class, used by the
  Hantush groundwater-mound convolution.
"""

from __future__ import annotations

from dataclasses import dataclass


# â”€â”€ Van Genuchten soil profile â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@dataclass(slots=True)
class VanGenuchtenSoilProfile:
    """Van Genuchten (1980) soil moisture retention parameters.

    Tabulated values from Carsel & Parrish (1988), WRR 24(5):755-769.
    Î± values converted from cmâ»Â¹ (Carsel) to mâ»Â¹ (Ã—100).
    Specific yield (S_y) values from Johnson (1967) and other references.

    Note: saturated hydraulic conductivity (K_s) is NOT stored here.
    SoakSIM uses the user-entered field-tested infiltration rate as K_s,
    consistent with the existing Argue (2004) methodology.
    """

    name: str
    theta_r: float        # residual water content (mÂ³/mÂ³)
    theta_s: float        # saturated water content (mÂ³/mÂ³)
    alpha_per_m: float    # van Genuchten Î± parameter (mâ»Â¹)
    n_vg: float           # van Genuchten n parameter (-)
    specific_yield: float # drainable porosity (-)

    @property
    def m_vg(self) -> float:
        """Van Genuchten m = 1 - 1/n."""
        return 1.0 - 1.0 / self.n_vg

    def effective_saturation(self, suction_head_m: float) -> float:
        """Effective saturation Sâ‚‘ = (Î¸ âˆ’ Î¸áµ£) / (Î¸â‚› âˆ’ Î¸áµ£).

        suction_head_m: positive value = unsaturated (pressure below atmospheric).
        Returns 1.0 for suction_head_m â‰¤ 0 (saturated conditions).
        """
        if suction_head_m <= 0.0:
            return 1.0
        denom = (1.0 + (self.alpha_per_m * suction_head_m) ** self.n_vg) ** self.m_vg
        return 1.0 / denom

    def theta(self, suction_head_m: float) -> float:
        """Water content Î¸(h) = Î¸áµ£ + (Î¸â‚› âˆ’ Î¸áµ£) Â· Sâ‚‘(h)."""
        return self.theta_r + (self.theta_s - self.theta_r) * self.effective_saturation(suction_head_m)

    def specific_yield_at(self, separation_m: float) -> float:
        """Effective specific yield at given soakwell-base-to-mound separation.

        Uses the three-point average moisture deficit (soakwell base, midpoint,
        water table) following Roldin et al. (2013).
        """
        h = max(0.0, separation_m)
        theta_avg = (self.theta(h) + self.theta(h / 2.0) + self.theta_s) / 3.0
        return max(0.01, self.theta_s - theta_avg)


# â”€â”€ Carsel & Parrish (1988) catalogue â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  (name,             Î¸áµ£,    Î¸â‚›,    Î± mâ»Â¹,  n,     S_y)
_RAW: tuple[tuple, ...] = (
    ("Sand",            0.045, 0.430, 14.50,  2.68,  0.27),
    ("Loamy Sand",      0.057, 0.410, 12.40,  2.28,  0.25),
    ("Sandy Loam",      0.065, 0.410,  7.50,  1.89,  0.20),
    ("Loam",            0.078, 0.430,  3.60,  1.56,  0.13),
    ("Silt Loam",       0.067, 0.450,  2.00,  1.41,  0.13),
    ("Silt",            0.034, 0.460,  1.60,  1.37,  0.10),
    ("Sandy Clay Loam", 0.100, 0.390,  5.90,  1.48,  0.13),
    ("Clay Loam",       0.095, 0.410,  1.90,  1.31,  0.08),
    ("Silty Clay Loam", 0.089, 0.430,  1.00,  1.23,  0.06),
    ("Sandy Clay",      0.100, 0.380,  2.70,  1.23,  0.05),
    ("Silty Clay",      0.070, 0.360,  0.50,  1.09,  0.04),
    ("Clay",            0.068, 0.380,  0.80,  1.09,  0.03),
)

SOIL_TEXTURE_CATALOGUE: dict[str, VanGenuchtenSoilProfile] = {
    row[0]: VanGenuchtenSoilProfile(
        name=row[0],
        theta_r=row[1],
        theta_s=row[2],
        alpha_per_m=row[3],
        n_vg=row[4],
        specific_yield=row[5],
    )
    for row in _RAW
}
