"""
================================================================================
VERSION CONTROL
================================================================================
File: gah_3d_engine.py
Version: 1.3.0
Date: 2026-07-01
Description: BaSIM Engine — Infiltration Routing + Hydraulic Structures

Built on the validated GAH-3D engine (phase 7 v1.2.0, phase 4 mechanics):
  Green-Ampt descending front + Hantush 3D groundwater mound, with the
  fixed-capacity overflow-reservoir vadose coupling and the back-calculation
  mound throttle (mound_rise_alpha=0 default, peak-preserving).

Divergence from the validated GAH-3D engine:
  The BaSIM Engine adds hydraulic outflow structures (weirs, culverts, grated
  pits) that extract water from the SURFACE storage. These operate AFTER
  infiltration in the routing mass balance:
      stored = inflow - infiltration - structure_outflow
  The infiltration + Hantush mounding mechanics are UNCHANGED — the structures
  do not touch the vadose-zone state (F, Z_f) or the mound (H_m). This
  preserves the phase 4 validation chain: the GAH-3D mechanics remain
  validated vs FiPy Richards; the structures are a surface-balance add-on.

See structures.py for the weir/culvert/pit outflow calculators and the
rock-lining design tool.
================================================================================
"""

import numpy as np
from scipy.special import erf

class GAH3D_Basin:
    """
    BaSIM Engine — infiltration + mounding core.

    (Class name kept as GAH3D_Basin for import compatibility; this IS the
    BaSIM Engine. See module docstring for the validation-chain rationale.)

    Couples the descending unsaturated wetting front (Green-Ampt) with the
    ascending saturated groundwater mound beneath a rectangular basin footprint
    (Hantush, 1967). Hydraulic outflow structures (weirs, culverts, grated pits)
    are handled by the caller on the surface storage — they do not enter this
    class. See structures.py.
    """
    def __init__(self, Ks, psi, Sy, b, L, W, D_gw, Kh=None, k_cl=None, l_cl=None,
                 slope=0.0, enable_batters=False, theta_deficit=None,
                 mound_rise_alpha=0.0):
        """
        Initialize the GAH-3D Basin parameters.

        Parameters:
        Ks   : Saturated Hydraulic Conductivity (m/s)
        psi  : Effective Capillary Drive (m) -- Warrick (1974) integral of kr
        Sy   : Specific Yield / drainable porosity used by the Hantush mound (-)
        b    : Aquifer saturated thickness (m)
        L    : Length of rectangular basin (m)
        W    : Width of rectangular basin (m)
        D_gw : Initial depth to groundwater table (m)
        Kh   : Optional horizontal hydraulic conductivity (m/s). Defaults to Ks.
        k_cl : Optional clogged layer hydraulic conductivity (m/s)
        l_cl : Optional clogged layer thickness (m)
        slope         : Side slope (H:V) e.g., 3.0 for 3H:1V
        enable_batters: Boolean to turn on/off dynamic footprint expansion
        theta_deficit : Vadose-zone moisture deficit (dtheta) for the Green-Ampt
            wetting front and the unsaturated storage capacity. Defaults to Sy
            (single-porosity, matching the phase 4 GAH-2D baseline). The split
            (dtheta for the front, Sy for the mound) is the more general form.
        mound_rise_alpha: Permitted mound rise above the basin bottom, as a
            fraction of the ponded depth (target cap = D_gw + alpha*h_pond).
            alpha=0.0 (DEFAULT, peak-preserving): mound pinned at the basin
            bottom once it reaches it; recharge damped to the lateral-drainage
            (Hantush) rate; conservative recession. Matches the phase 4 shipped
            default. alpha>0 lets the mound rise into the ponded column for a
            faster recession at the cost of a lower peak.
        """
        self.Ks = Ks
        self.psi = psi
        self.Sy = Sy
        # Green-Ampt porosity (dtheta): fillable porosity of the unsaturated
        # column above the water table. Distinct from Sy (drainable porosity
        # used by the Hantush mound). Defaults to Sy when not supplied, which
        # reproduces the phase 4 GAH-2D single-porosity formulation exactly.
        self.theta_deficit = theta_deficit if (theta_deficit is not None and theta_deficit > 0) else Sy
        self.b = b
        self.Kh = Kh if Kh is not None else Ks
        self.T = self.Kh * self.b
        self.L = L
        self.W = W
        self.D_gw = D_gw
        self.k_cl = k_cl
        self.l_cl = l_cl
        self.slope = slope
        self.enable_batters = enable_batters
        self.mound_rise_alpha = mound_rise_alpha

        # Aquifer diffusivity (uses Sy -- the drainable porosity for the mound)
        self.alpha = self.T / self.Sy

        # State variables
        self.Z_f = 0.0      # Wetting front depth (m) -- derived from F / dtheta
        self.H_m = 0.0      # Mound height above initial water table (m)
        self.time = 0.0     # Simulation time (s)

        # Cumulative infiltration into the vadose zone (m of water per unit
        # area, UNBOUNDED). This is the phase 4 GAH-2D state variable F: the
        # wetting-front depth is z_wf = F / dtheta, and the vadose column's
        # FIXED capacity is D_gw * dtheta. The mound throttles the infiltration
        # FLUX (via the saturated GA gradient and the Hantush back-calculation)
        # but does NOT shrink the vadose storage capacity -- this is the key
        # difference from the phase 10 web-app engine, whose mound-coupled
        # capacity (D_gw - H_m)*dtheta requires an upstream logistic-blend
        # throttle instead. The fixed-capacity + back-calc pairing is
        # mass-conserving by construction (F = deficit_filled + cum_recharge)
        # and avoids the squeeze/exfiltration feedback that a mound-coupled
        # capacity would create under a back-calculation throttle.
        self.F = 0.0

        # History arrays for the Hantush time-superposition (convolution)
        self.t_history = []
        self.R_history = []
        self.L_history = []
        self.W_history = []

        # Mass-balance accumulators (phase 4 subsurface identity:
        # F = deficit_filled + cum_recharge, exact by construction)
        self.cum_inflow = 0.0     # cumulative infiltration entering the soil (= F)
        self.cum_recharge = 0.0   # cumulative recharge reaching the water table (m)

    def predict_potential_infil(self, dt, current_ponding_depth):
        """
        Predict the soil's POTENTIAL infiltration capacity (m/s) for this step
        WITHOUT modifying any state. The caller must cap this to the available
        surface water (ponded + inflow during the step) before committing via
        update_state(). This split mirrors the phase 10 web-app engine and is
        essential for mass conservation: the engine advances its vadose/mound
        state on the ACTUAL (capped) flux, not the uncapped potential.

        Returns:
        f_potential_base : Potential infiltration flux (m/s), per unit BASE area.
        """
        h = current_ponding_depth

        # Effective (batter-expanded) footprint for this step
        if self.enable_batters and self.slope > 0:
            L_eff = self.L + 2.0 * h * self.slope
            W_eff = self.W + 2.0 * h * self.slope
        else:
            L_eff = self.L
            W_eff = self.W

        # ---- Phase 4 GAH-2D mechanics ported to the 3D rectangular kernel ----
        dtheta = self.theta_deficit
        L = self.D_gw                       # static water-table depth (phase 4 "L")
        F_old = self.F                      # cumulative infiltration (phase 4 "F")
        z_wf = F_old / dtheta if dtheta > 0 else 0.0

        # ---- 1. Green-Ampt potential flux (descending front) ----------------
        if z_wf >= L:
            # Saturated connection: the mound throttles via the Darcy gradient
            # from the ponded surface through the saturated column to the water
            # table. fp = Ks * (L + h - H_m) / L. (Phase 4 fp_sat, with the
            # ponding head h included -- phase 4 uses SH, the same quantity.)
            fp = self.Ks * (L + h - self.H_m) / L
            fp = max(0.0, fp)
        else:
            # Unsaturated Green-Ampt. Phase 4 uses fp = Ks*(1 + psi*dtheta/F)
            # WITHOUT the ponding head; we add h to the capillary-drive term
            # (standard GA form) as a documented, legitimate improvement.
            if F_old <= 1e-10:
                fp = 1.0e9       # infinite initial suction (phase 4: fp = 1000)
            else:
                fp = self.Ks * (1.0 + (self.psi * dtheta + h) / F_old)
        f_potential = fp

        # Clogged-layer cap (Darcy through the clogging skin; with batters the
        # side/corner batter areas are included, matching the legacy CloggedModel).
        if self.k_cl is not None and self.l_cl is not None and self.l_cl > 0:
            if self.enable_batters:
                base_term = self.L * self.W * (h + self.l_cl) / self.l_cl
                side_term = 2.0 * h * (self.L + self.W) * np.sqrt(1.0 + self.slope**2) * (0.5 * h + self.l_cl) / self.l_cl
                corner_term = 4.0 * (h**2) * self.slope * np.sqrt(1.0 + self.slope**2) * (h / 3.0 + self.l_cl) / self.l_cl
                f_clogged = self.k_cl * (base_term + side_term + corner_term) / (L_eff * W_eff)
            else:
                f_clogged = self.k_cl * (h + self.l_cl) / self.l_cl
            f_potential = min(f_potential, f_clogged)

        # Flux expressed per unit BASE area so the caller's (f * L * W * dt)
        # equals the true 3D volumetric infiltration through the footprint.
        f_potential_base = f_potential * (L_eff * W_eff) / (self.L * self.W)
        return f_potential_base

    def step(self, dt, current_ponding_depth, available_water_depth=None):
        """
        Advance the simulation by one time step.

        This is the phase 4 GAH-2D mechanics -- GA capacity, available-water
        limit, vadose breakthrough (fixed capacity), Hantush 3D mound
        convolution, and the back-calculation mound throttle -- ported to the
        3D rectangular kernel, executed in a single consistent pass so that
        the available-water cap and the mound throttle never conflict (the
        circular-dependency pitfall of a predict/update split).

        Parameters:
        dt : Time step duration (s)
        current_ponding_depth : Transient surface ponding depth (m)
        available_water_depth : Total water depth available to infiltrate this
            step (m) = ponded depth + inflow depth (q_in*dt/area). If None,
            self-limits to the ponded depth h only (constant-ponding tests).

        Returns:
        f_actual_base : Actual infiltration flux (m/s) per unit BASE area,
            already capped to available water AND mound-throttled. The caller's
            (f * L * W * dt) equals the true 3D volumetric infiltration.
        """
        self.time += dt
        h = current_ponding_depth

        # Effective (batter-expanded) footprint for this step
        if self.enable_batters and self.slope > 0:
            L_eff = self.L + 2.0 * h * self.slope
            W_eff = self.W + 2.0 * h * self.slope
        else:
            L_eff = self.L
            W_eff = self.W

        # ---- Phase 4 GAH-2D mechanics ported to the 3D rectangular kernel ----
        dtheta = self.theta_deficit
        L = self.D_gw                       # static water-table depth (phase 4 "L")
        F_old = self.F                      # cumulative infiltration (phase 4 "F")
        z_wf = F_old / dtheta if dtheta > 0 else 0.0
        col_capacity = L * dtheta           # FIXED vadose capacity (phase 4)

        # ---- 1. Green-Ampt potential flux (descending front) ----------------
        if z_wf >= L:
            # Saturated connection: the mound throttles via the Darcy gradient
            # from the ponded surface through the saturated column to the water
            # table. fp = Ks * (L + h - H_m) / L. (Phase 4 fp_sat, with the
            # ponding head h included -- phase 4 uses SH, the same quantity.)
            fp = self.Ks * (L + h - self.H_m) / L
            fp = max(0.0, fp)
        else:
            # Unsaturated Green-Ampt. Phase 4 uses fp = Ks*(1 + psi*dtheta/F)
            # WITHOUT the ponding head; we add h to the capillary-drive term
            # (standard GA form) as a documented, legitimate improvement.
            if F_old <= 1e-10:
                fp = 1.0e9       # infinite initial suction (phase 4: fp = 1000)
            else:
                fp = self.Ks * (1.0 + (self.psi * dtheta + h) / F_old)
        f_potential = fp

        # Clogged-layer cap (Darcy through the clogging skin; with batters the
        # side/corner batter areas are included, matching the legacy CloggedModel).
        if self.k_cl is not None and self.l_cl is not None and self.l_cl > 0:
            if self.enable_batters:
                base_term = self.L * self.W * (h + self.l_cl) / self.l_cl
                side_term = 2.0 * h * (self.L + self.W) * np.sqrt(1.0 + self.slope**2) * (0.5 * h + self.l_cl) / self.l_cl
                corner_term = 4.0 * (h**2) * self.slope * np.sqrt(1.0 + self.slope**2) * (h / 3.0 + self.l_cl) / self.l_cl
                f_clogged = self.k_cl * (base_term + side_term + corner_term) / (L_eff * W_eff)
            else:
                f_clogged = self.k_cl * (h + self.l_cl) / self.l_cl
            f_potential = min(f_potential, f_clogged)

        # ---- 1b. Available-water limit (phase 4: f = min(fp, avail_water)) ---
        # Cap the potential to the water actually on the surface this step.
        if available_water_depth is not None:
            f_avail = available_water_depth / dt
        else:
            f_avail = h / dt if h > 0 else 0.0
        f_actual = min(f_potential, f_avail)

        # ---- 2. Vadose breakthrough (phase 4 volume balance, fixed capacity) -
        # Before breakthrough (z_wf < L): infiltration first fills the remaining
        # vadose capacity; only the overflow becomes recharge. After
        # breakthrough (z_wf >= L): all infiltration becomes recharge.
        if z_wf < L:
            vol_needed = col_capacity - F_old            # remaining vadose capacity
            vol_infiltrated = f_actual * dt
            if vol_infiltrated > vol_needed:
                w_tent = (vol_infiltrated - vol_needed) / dt
            else:
                w_tent = 0.0
        else:
            w_tent = f_actual

        # ---- 3. Hantush 3D ascending mound (linear rectangular kernel) -------
        # Convolution including the current step's tentative recharge so the
        # tentative mound can be evaluated and, if it exceeds the cap, the
        # limiting recharge back-calculated. This is the phase 4 GAH-2D
        # back-calculation throttle, ported to the linear Hantush kernel where
        # the inversion is trivial (the kernel is linear in R).
        t_arr = np.array(self.t_history + [self.time])
        R_arr = np.array(self.R_history + [w_tent])
        L_arr = np.array(self.L_history + [L_eff])
        W_arr = np.array(self.W_history + [W_eff])
        taus = np.maximum(self.time - t_arr, 1e-8)
        denom = np.sqrt(4.0 * self.alpha * taus)
        kernel = erf((L_arr / 2.0) / denom) * erf((W_arr / 2.0) / denom)
        H_tent = np.sum(R_arr * kernel) * (dt / self.Sy)

        # Mound cap: basin bottom (L = D_gw) plus the permitted rise
        # (alpha * h_pond). Phase 4: mound_target = L + alpha * SH.
        # alpha=0 (default) = peak-preserving hard cap (mound pinned at the
        # basin bottom; recharge damped to the lateral-drainage rate).
        H_cap = L + self.mound_rise_alpha * h

        if H_tent > H_cap:
            # Back-calculate the recharge rate that holds the mound at the cap.
            # Linear kernel: H_cap = (dt/Sy) * (past_sum + R_max * K_N)
            #   past_sum = sum of (R_j * K_j) over all PREVIOUS steps (j < N)
            #   K_N      = kernel value for the current step
            if len(self.R_history) > 0:
                past_sum = np.sum(np.array(self.R_history) * kernel[:-1])
            else:
                past_sum = 0.0
            K_N = kernel[-1]
            if K_N > 1e-12:
                R_max = (H_cap * self.Sy / dt - past_sum) / K_N
            else:
                R_max = 0.0
            R = min(w_tent, max(0.0, R_max))

            # Reduce the surface flux to match the capped recharge (phase 4):
            #   pre-breakthrough:  f = R + vol_needed/dt  (fill remaining column + capped recharge)
            #   post-breakthrough: f = R                  (all infiltration -> recharge)
            # f_actual_capped <= f_actual holds because R <= w_tent.
            if z_wf < L:
                f_actual_capped = R + vol_needed / dt
            else:
                f_actual_capped = R
            f_actual_capped = max(0.0, min(f_actual_capped, f_actual))
            H_m_new = H_cap
        else:
            R = w_tent
            f_actual_capped = f_actual
            H_m_new = H_tent

        # ---- 4. Commit state + history --------------------------------------
        # NOTE: self.F and cum_recharge are per FOOTPRINT area (L_eff*W_eff);
        # cum_inflow is per BASE area (L*W) so the caller's mass balance
        # (cum_in * area_base = V_final + cum_inflow * area_base) closes exactly.
        f_actual_base = f_actual_capped * (L_eff * W_eff) / (self.L * self.W)
        self.F += f_actual_capped * dt             # cumulative infiltration per footprint area (unbounded)
        self.cum_inflow += f_actual_base * dt       # cumulative infiltration per BASE area
        self.Z_f = min(self.F / dtheta, L)         # wetting-front depth (capped at water table)
        self.H_m = H_m_new
        self.t_history.append(self.time)
        self.R_history.append(R)
        self.L_history.append(L_eff)
        self.W_history.append(W_eff)
        self.cum_recharge += R * dt                 # recharge per footprint area (matches Hantush kernel)

        return f_actual_base

if __name__ == "__main__":
    # Rapid Unit Verification Test
    print("Initializing GAH-3D Engine Verification...")

    Ks = 5e-5       # 50 mm/hr
    psi = 0.1       # 100 mm suction head
    Sy = 0.25       # 25% specific yield
    b = 10.0        # 10m aquifer thickness
    L = 20.0        # 20m long basin
    W = 10.0        # 10m wide basin
    D_gw = 3.0      # 3m depth to groundwater

    basin = GAH3D_Basin(Ks=Ks, psi=psi, Sy=Sy, b=b, L=L, W=W, D_gw=D_gw)

    dt = 60         # 1 minute time steps
    sim_hours = 12
    steps = int(sim_hours * 3600 / dt)

    current_ponding_depth = 0.5  # Constant half-meter ponding

    for i in range(steps):
        f = basin.step(dt, current_ponding_depth)

        if (i + 1) % 60 == 0:
            hr = (i + 1) / 60
            sep = max(0.0, D_gw - basin.H_m - basin.Z_f)
            print(f"Hr {hr:02.0f} | f: {f*3600*1000:6.1f} mm/hr | Z_f: {basin.Z_f:4.2f} m | "
                  f"H_m: {basin.H_m:4.2f} m | Sep: {sep:4.2f} m")

    # Mass-balance check (phase 4 subsurface identity: F = deficit_filled + cum_recharge)
    col_capacity = D_gw * basin.theta_deficit
    deficit_filled = min(basin.F, col_capacity)
    sub_resid = basin.F - (deficit_filled + basin.cum_recharge)
    print(f"\nSubsurface | F={basin.F:6.4f} m | deficit_filled={deficit_filled:6.4f} m | "
          f"recharge={basin.cum_recharge:6.4f} m | residual={sub_resid:.3e} m")
    print(f"Surface    | cum_inflow(base)={basin.cum_inflow:6.4f} m | residual={basin.cum_inflow - basin.F * (basin.L*basin.W)/(basin.L*basin.W):.3e} m")
    print("Verification complete.")
