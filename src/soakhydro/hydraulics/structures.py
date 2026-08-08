"""
================================================================================
VERSION CONTROL
================================================================================
File: structures.py
Version: 1.0.0
Date: 2026-07-01
Description: BaSIM Engine — Hydraulic Outflow Structures

Outflow calculators for weirs, culverts, and grated pits that extract water
from the basin's surface storage. Each calculator takes the current water
depth (above basin invert) and the structure parameters, and returns the
outflow rate (m³/s). The basin router caps the total
structure outflow to the available surface storage.

These operate on the SURFACE balance only — they do not touch the vadose-zone
state (F, Z_f) or the Hantush mound (H_m). This preserves the validation
chain: the GAH-3D infiltration/mounding mechanics remain validated vs FiPy.

References:
  - Broad-crested weir: Henderson (1966), Bos (1989)
  - Culvert (HY-8): FHWA HIF-12-026 (2012), Norman et al.
  - Grated pit: QUDM (2013) §7.6, pp 7-30 to 7-33 (surcharge pits)
  - Rock lining: Catchments & Creeks (2023), Fact Sheets 5/6/8/7
================================================================================
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

# Physical constants
G = 9.81          # gravitational acceleration (m/s²)
GAMMA_W = 9810.0  # specific weight of water (N/m³)
SG_ROCK = 2.65    # specific gravity of rock (quartz)


# ── Broad-crested weir ────────────────────────────────────────────────────

# Discharge coefficients by lining type (Henderson 1966; Bos 1989).
# These are C_d in Q = C_d * L * H^1.5 (SI units: Q in m³/s, L & H in m).
WEIR_CD = {
    "bare_earth": 1.32,   # rough earth, lower efficiency
    "concrete":   1.71,   # smooth, well-formed crest
    "rock_lined": 1.49,   # rock-lined crest, intermediate roughness
}


@dataclass(slots=True)
class BroadCrestedWeir:
    """Broad-crested weir outflow calculator.

    Q = C_d * L * H^1.5, where H = head above crest = max(0, water_depth - crest_height).
    The crest height is relative to the basin invert (i.e., water_depth is also
    relative to the basin invert, so crest_height is the weir's elevation above
    the basin floor).

    Parameters:
        crest_height_m : weir crest elevation above basin invert (m)
        length_m       : weir crest length perpendicular to flow (m)
        lining         : "bare_earth" | "concrete" | "rock_lined"
    """
    crest_height_m: float
    length_m: float
    lining: str = "concrete"

    def outflow_m3s(self, water_depth_m: float) -> float:
        """Return the weir outflow rate (m³/s). Zero if water below crest."""
        H = water_depth_m - self.crest_height_m
        if H <= 0.0:
            return 0.0
        C_d = WEIR_CD.get(self.lining, 1.49)
        return C_d * self.length_m * H ** 1.5


# ── Culvert (HY-8 inlet + outlet control) ────────────────────────────────

# Manning's roughness by material (FHWA HIF-12-026, Table 3).
CULVERT_MANNINGS_N = {
    "RCP":  0.012,   # Reinforced Concrete Pipe (precast, smooth)
    "PVC":  0.010,   # Polyvinyl Chloride (smooth, low friction)
    "CSP":  0.024,   # Corrugated Steel Pipe (helical/annular corrugations)
    "RCBC": 0.013,   # Reinforced Concrete Box Culvert (cast, smooth-ish)
}

# Standard circular culvert diameters (mm) — typical manufacturer sizes.
CULVERT_DIAMETERS_MM = [
    300, 375, 450, 525, 600, 675, 750, 825, 900,
    1050, 1200, 1350, 1500, 1650, 1800, 2100, 2400,
]

# Inlet-control discharge coefficients by material (FHWA nomograph form).
# These are the "c" and "Y" parameters in Q = c * A * (HW/D)^Y for inlet control
# (unsubmerged, equation 1 of HIF-12-026). Simplified to a single orifice-style
# coefficient C_d for the screening tool, tuned per material roughness.
INLET_CONTROL_CD = {
    "RCP":  0.62,   # square-edged inlet, concrete (mitered would be ~0.75)
    "PVC":  0.60,   # similar to RCP, slightly lower for typical beveled inlet
    "CSP":  0.55,   # corrugated, projectng inlet — lower efficiency
    "RCBC": 0.65,   # box culvert, square-edged to slightly beveled
}


@dataclass(slots=True)
class Culvert:
    """Culvert outflow calculator (HY-8 inlet + outlet control).

    Computes both inlet-control (orifice) and outlet-control (Manning's) capacity,
    and returns the MINIMUM (the governing control). The culvert invert is
    relative to the basin invert (same datum as water_depth_m).

    Parameters:
        material           : "RCP" | "PVC" | "CSP" | "RCBC"
        diameter_mm        : internal diameter for circular culverts (mm)
        width_mm           : internal width for RCBC box culverts (mm)
        height_mm          : internal height for RCBC box culverts (mm)
        invert_height_m    : culvert invert elevation above basin invert (m)
        length_m           : culvert barrel length (m)
        slope              : culvert barrel slope (m/m, positive = downhill)
        count              : number of barrels (multi-barrel culverts)
        tailwater_m        : tailwater depth above culvert invert at outlet (m).
                             Default 0.0 = free outfall (conservative).
    """
    material: str
    invert_height_m: float
    length_m: float = 10.0
    slope: float = 0.0
    count: int = 1
    diameter_mm: Optional[int] = None
    width_mm: Optional[int] = None
    height_mm: Optional[int] = None
    tailwater_m: float = 0.0

    def _area_m2(self) -> float:
        """Cross-sectional flow area (m²) for one barrel."""
        if self.material == "RCBC":
            w = (self.width_mm or 600) / 1000.0
            h = (self.height_mm or 450) / 1000.0
            return w * h
        else:
            d = (self.diameter_mm or 450) / 1000.0
            return math.pi * d * d / 4.0

    def _hydraulic_radius_m(self) -> float:
        """Hydraulic radius (m) for full-barrel flow."""
        if self.material == "RCBC":
            w = (self.width_mm or 600) / 1000.0
            h = (self.height_mm or 450) / 1000.0
            return w * h / (2.0 * (w + h))
        else:
            d = (self.diameter_mm or 450) / 1000.0
            return d / 4.0

    def _outlet_control_q(self, head_m: float) -> float:
        """Outlet-control capacity (m³/s) via Manning's equation with friction +
        entrance losses. head_m = water depth above culvert invert.

        For full-pipe flow: H_loss = (1 + Ke + 29*n²*L / R^(4/3)) * V² / (2g)
        Solve for V, then Q = A * V * count.
        """
        if head_m <= 0.0:
            return 0.0
        n = CULVERT_MANNINGS_N.get(self.material, 0.012)
        A = self._area_m2()
        R = self._hydraulic_radius_m()
        Ke = 0.5  # entrance loss coefficient (square-edged)

        # Available head for friction = total head - tailwater (driving head)
        hw = max(head_m - self.tailwater_m, 0.0)
        if hw <= 0.0:
            return 0.0

        # H_loss = (Ke + 1 + friction) * V²/(2g), friction = 29 * n² * L / R^(4/3)
        # (the 29 = 2 * 14.5 = 2 * (1.49² in US units → SI: 2*12.09 ≈ 24.2... actually
        #  in SI Manning's, friction loss = (n² * L / R^(4/3)) * V² * 2g is not quite right.
        #  The correct SI form: H_f = (n² * L / R^(4/3)) * V² * 2g / (2g) ... let me use
        #  the standard: H_f = (29.16 * n² * L / R^(4/3)) * V² / (2g) — no.
        #  Standard SI: friction slope S_f = (n * V / R^(2/3))², so H_f = S_f * L.
        #  Total H = (Ke + 1) * V²/(2g) + S_f * L. Solve: V = sqrt(2g*H / (Ke+1 + 2g*n²*L/R^(4/3))))
        denom = (Ke + 1.0) + (2.0 * G * n * n * self.length_m / R ** (4.0 / 3.0))
        V = math.sqrt(2.0 * G * hw / max(denom, 1e-12))
        return A * V * self.count

    def _inlet_control_q(self, head_m: float) -> float:
        """Inlet-control capacity (m³/s) — orifice equation.
        Q = C_d * A * sqrt(2g*H) * count, H = head above invert.
        """
        if head_m <= 0.0:
            return 0.0
        C_d = INLET_CONTROL_CD.get(self.material, 0.62)
        A = self._area_m2()
        H = max(head_m - self.tailwater_m, 0.0)
        if H <= 0.0:
            return 0.0
        return C_d * A * math.sqrt(2.0 * G * H) * self.count

    def outflow_m3s(self, water_depth_m: float) -> float:
        """Return the governing (minimum) culvert outflow rate (m³/s)."""
        head = water_depth_m - self.invert_height_m
        if head <= 0.0:
            return 0.0
        q_inlet = self._inlet_control_q(head)
        q_outlet = self._outlet_control_q(head)
        return min(q_inlet, q_outlet)


# ── Grated pit (QUDM 2013 surcharge) ─────────────────────────────────────

@dataclass(slots=True)
class GratedPit:
    """Grated surcharge pit outflow calculator (QUDM 2013, §7.6, pp 7-30→7-33).

    A surcharge pit acts as an orifice (flow through the grate openings under
    submergence) and/or a weir (flow over the grate perimeter at low head).

    Parameters:
        inlet_height_m  : grate inlet elevation above basin invert (m)
        length_m        : grate length (m)
        width_m         : grate width (m)
        opening_ratio   : fraction of grate area that is open (0–1, default 0.5)
    """
    inlet_height_m: float
    length_m: float
    width_m: float
    opening_ratio: float = 0.5

    def outflow_m3s(self, water_depth_m: float) -> float:
        """Return the pit outflow rate (m³/s).

        QUDM surcharge pit: when the water is above the grate inlet, flow exits
        through the open grate area as an orifice (high head) and over the
        perimeter as a weir (low head / unsubmerged). We take the orifice flow
        as the governing capacity for a surcharge pit (conservative for design).
        """
        H = water_depth_m - self.inlet_height_m
        if H <= 0.0:
            return 0.0

        grate_area = self.length_m * self.width_m
        open_area = grate_area * self.opening_ratio
        perimeter = 2.0 * (self.length_m + self.width_m)

        # Orifice flow through the open grate (QUDM surcharge, submerged grate)
        C_d_orifice = 0.61
        q_orifice = C_d_orifice * open_area * math.sqrt(2.0 * G * H)

        # Weir flow over the grate perimeter (QUDM, low-head / unsubmerged)
        C_d_weir = 1.7  # broad-crested weir coefficient
        q_weir = C_d_weir * perimeter * H ** 1.5

        # The pit capacity is the orifice flow when submerged (deep water),
        # and the weir flow when the head is small (water just over the grate).
        # For a screening tool, take the MINIMUM (conservative — the structure
        # can't pass more than either mode allows).
        return min(q_orifice, q_weir)


# ── Rock lining design (Catchments & Creeks) ─────────────────────────────

@dataclass(slots=True)
class RockLiningDesign:
    """Rock sizing for batter chutes, weir spillways, and toe protection.

    Based on Catchments & Creeks (2023) Fact Sheets:
      - FS6: Rock Sizing for Batter Chutes
      - FS8: Rock Sizing for Small Dam Spillways
      - FS5: Rock Sizing for Batter Chute Outlets

    Two methods are provided; the velocity-based method is used by default
    (it's the more common screening approach for stormwater structures):

      Velocity-based:   d50 = K * V² / (2g * (SG-1) * cos(tan⁻¹(S)))
      Shear-stress:     d50 = τ / (τ*_c * (SG-1) * γ_w)
        where τ = γ_w * h * S (bed shear), τ*_c = 0.047 (Shields)

    Parameters:
        velocity_ms   : design flow velocity over the lining (m/s)
        depth_m       : flow depth over the lining (m, for shear-stress method)
        slope         : chute/batter slope (m/m, e.g. 0.33 for 3H:1V)
        shape_factor  : K (default 1.2, catchments&creeks recommended for rock)
    """
    velocity_ms: float
    depth_m: float = 0.3
    slope: float = 0.33
    shape_factor: float = 1.2

    def d50_velocity_mm(self) -> float:
        """Recommended median rock size (mm) — velocity-based method."""
        cos_theta = 1.0 / math.sqrt(1.0 + self.slope ** 2)
        d50_m = (self.shape_factor * self.velocity_ms ** 2) / \
                (2.0 * G * (SG_ROCK - 1.0) * cos_theta)
        return d50_m * 1000.0

    def d50_shear_mm(self) -> float:
        """Recommended median rock size (mm) — shear-stress method.

        Uses the Catchments & Creeks permissible-shear approach for rock lining
        (not the Shields incipient-motion threshold, which is for sand/gravel
        and gives unreasonably large d50 for stormwater velocities). The
        permissible shear stress for rock is approximated as:
            τ_permissible ≈ 0.7 * (SG - 1) * γ_w * d50   (Isbash-style)
        Rearranging: d50 = τ_applied / (0.7 * (SG-1) * γ_w)
        """
        tau = GAMMA_W * self.depth_m * self.slope  # applied bed shear (Pa)
        coeff = 0.7 * (SG_ROCK - 1.0) * GAMMA_W
        d50_m = tau / coeff
        return d50_m * 1000.0

    def d50_governing_mm(self) -> float:
        """Governing (maximum) d50 from both methods — conservative for design."""
        return max(self.d50_velocity_mm(), self.d50_shear_mm())

    def layer_thickness_mm(self) -> float:
        """Minimum layer thickness = 1.5 × d50 (catchments&creeks)."""
        return 1.5 * self.d50_governing_mm()

    def gradation_band(self) -> dict:
        """Typical rock gradation band (catchments&creeks Table 1)."""
        d50 = self.d50_governing_mm()
        return {
            "d50_mm": round(d50, 0),
            "d100_mm": round(d50 * 2.0, 0),
            "d15_mm": round(d50 * 0.15, 0),
            "layer_thickness_mm": round(self.layer_thickness_mm(), 0),
        }


# ── Factory: build structure objects from API request ────────────────────

def build_structure(struct_dict: dict) -> BroadCrestedWeir | Culvert | GratedPit:
    """Build a structure outflow calculator from a HydraulicStructureIn dict.

    The basin_invert_m_ahd is subtracted from the user's AHD levels to convert
    to "height above basin invert" (which is the datum the routing loop uses
    for water_depth_m).
    """
    stype = struct_dict.get("type", "")
    basin_invert = struct_dict.get("_basin_invert_m_ahd", 0.0)

    if stype == "weir":
        crest_ahd = struct_dict.get("weir_crest_level_m_ahd", basin_invert)
        return BroadCrestedWeir(
            crest_height_m=crest_ahd - basin_invert,
            length_m=struct_dict.get("weir_length_m", 1.0),
            lining=struct_dict.get("weir_lining", "concrete"),
        )
    elif stype == "culvert":
        invert_ahd = struct_dict.get("culvert_invert_level_m_ahd", basin_invert)
        return Culvert(
            material=struct_dict.get("culvert_material", "RCP"),
            invert_height_m=invert_ahd - basin_invert,
            length_m=struct_dict.get("culvert_length_m", 10.0),
            slope=struct_dict.get("culvert_slope", 0.0),
            count=struct_dict.get("culvert_count", 1),
            diameter_mm=struct_dict.get("culvert_diameter_mm"),
            width_mm=struct_dict.get("culvert_width_mm"),
            height_mm=struct_dict.get("culvert_height_mm"),
        )
    elif stype == "grated_pit":
        inlet_ahd = struct_dict.get("pit_inlet_level_m_ahd", basin_invert)
        return GratedPit(
            inlet_height_m=inlet_ahd - basin_invert,
            length_m=struct_dict.get("pit_length_m", 0.6),
            width_m=struct_dict.get("pit_width_m", 0.6),
            opening_ratio=struct_dict.get("pit_opening_ratio", 0.5),
        )
    else:
        raise ValueError(f"Unknown structure type: {stype}")


def compute_structure_outflows(
    structures: list,
    water_depth_m: float,
    dt_s: float,
    available_storage_m3: float,
) -> tuple[float, list[float]]:
    """Compute the total structure outflow volume for one timestep.

    Parameters:
        structures            : list of structure objects (BroadCrestedWeir/Culvert/GratedPit)
        water_depth_m         : current water depth above basin invert (m)
        dt_s                  : timestep duration (s)
        available_storage_m3  : current stored volume (m³) — outflow capped to this

    Returns:
        (total_outflow_vol_m3, [per_structure_outflow_vol_m3, ...])
    """
    per_structure = []
    total_q = 0.0
    for struct in structures:
        q = struct.outflow_m3s(water_depth_m)
        per_structure.append(q * dt_s)
        total_q += q

    total_vol = min(total_q * dt_s, available_storage_m3)
    # Scale per-structure volumes proportionally if capped
    if total_q * dt_s > available_storage_m3 and total_q > 0:
        scale = available_storage_m3 / (total_q * dt_s)
        per_structure = [v * scale for v in per_structure]

    return total_vol, per_structure
