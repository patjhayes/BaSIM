/* ── SoakSIM Dashboard — frontend logic ─────────────────────────────── */



    let simulationData = null;
    let lastSimRequest = null;   // exact body of the last /api/simulate run — reused by clogging so year 0 matches
    let resultsLocked = false;   // when true, design inputs are locked until results are cleared
    let basinSoilProfiles = {};

    const APP_CONFIG = window.BASIM_CONFIG || {};
    const configuredValue = (value) =>
      value && !String(value).startsWith("%VITE_") ? String(value) : "";
    const API_BASE = configuredValue(APP_CONFIG.apiUrl).replace(/\/$/, "");
    const apiUrl = (path) => `${API_BASE}${path}`;

    // ── Supabase auth ────────────────────────────────────────────────────
    // The dashboard requires a valid Supabase session. Anonymous reference
    // GETs (catalogue, soil profiles) remain public, but the compute endpoints
    // (/api/simulate, /api/v1/gah_clogging) require a Bearer access token.
    const SUPABASE_URL = configuredValue(APP_CONFIG.supabaseUrl);
    const SUPABASE_ANON_KEY = configuredValue(APP_CONFIG.supabaseAnonKey);
    let supabaseClient = null;
    try {
      if (window.supabase && SUPABASE_URL && SUPABASE_ANON_KEY) {
        supabaseClient = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
      }
    } catch (err) {
      console.error("Supabase client init failed", err);
    }

    /** Returns the current access token, or null if not signed in. */
    async function getAccessToken() {
      if (!supabaseClient) return null;
      const { data } = await supabaseClient.auth.getSession();
      return data && data.session ? data.session.access_token : null;
    }

    /** Auth header for protected fetch calls, or an empty object. */
    async function authHeaders(extra = {}) {
      const token = await getAccessToken();
      const h = { ...extra };
      if (token) h["Authorization"] = `Bearer ${token}`;
      return h;
    }

    /** Gate the dashboard: redirect to login.html if no session. */
    async function requireSession() {
      if (!supabaseClient) {
        window.location.href = "./login.html?reason=configuration";
        return;
      }
      const token = await getAccessToken();
      if (!token) {
        window.location.href = "./login.html";
      }
    }

    /** Wire the Logout link to sign out and redirect. */
    function wireLogout() {
      const link = document.getElementById("auth-link");
      if (!link) return;
      link.addEventListener("click", async (e) => {
        e.preventDefault();
        if (supabaseClient) {
          try { await supabaseClient.auth.signOut(); } catch (err) { console.warn(err); }
        }
        window.location.href = "./login.html";
      });
    }

    // Run the session gate + logout wiring once the DOM is ready.
    document.addEventListener("DOMContentLoaded", () => {
      requireSession();
      wireLogout();
    });

    const BASIN_SOIL_DEFAULTS = {
      "Sand": { deficit: 0.20, suction: 0.10, specificYield: 0.27 },
      "Loamy Sand": { deficit: 0.19, suction: 0.12, specificYield: 0.25 },
      "Sandy Loam": { deficit: 0.18, suction: 0.14, specificYield: 0.20 },
      "Loam": { deficit: 0.17, suction: 0.16, specificYield: 0.13 },
      "Silt Loam": { deficit: 0.16, suction: 0.18, specificYield: 0.13 },
      "Silt": { deficit: 0.16, suction: 0.20, specificYield: 0.10 },
      "Sandy Clay Loam": { deficit: 0.15, suction: 0.20, specificYield: 0.13 },
      "Clay Loam": { deficit: 0.14, suction: 0.22, specificYield: 0.08 },
      "Silty Clay Loam": { deficit: 0.13, suction: 0.24, specificYield: 0.06 },
      "Sandy Clay": { deficit: 0.13, suction: 0.24, specificYield: 0.05 },
      "Silty Clay": { deficit: 0.12, suction: 0.26, specificYield: 0.04 },
      "Clay": { deficit: 0.12, suction: 0.28, specificYield: 0.03 },
    };

    function getStructureType() {
      return "basin";
    }

    function getStructureLabel(type) {
      return "Basin";
    }

    // ── Hydraulic structures management ────────────────────────────────
    // The structures are stored in a global array; each is a plain object
    // matching the HydraulicStructureIn schema. The 3D scene reads them via
    // window._getBasimStructures.
    let basimStructures = [];
    window._getBasimStructures = function() { return basimStructures; };

    function toggleStructuresUI() {
      const enabled = document.getElementById("inp-structures-enabled").checked;
      document.getElementById("structures-config").style.display = enabled ? "" : "none";
      if (typeof updateSceneFromInputs === "function") updateSceneFromInputs();
    }

    function addStructure() {
      const typeSelect = document.getElementById("inp-structure-type");
      const type = typeSelect.value;
      const invertAHD = parseFloat(document.getElementById("inp-surface-lvl").value) || 10.0;
      const maxDepth = parseFloat(document.getElementById("inp-basin-depth").value) || 1.2;
      const surfaceAHD = invertAHD + maxDepth;

      let struct = { type: type, name: type.charAt(0).toUpperCase() + type.slice(1) + " " + (basimStructures.length + 1) };
      if (type === "weir") {
        struct.weir_crest_level_m_ahd = surfaceAHD - 0.2;
        struct.weir_length_m = 2.0;
        struct.weir_lining = "concrete";
      } else if (type === "culvert") {
        struct.culvert_material = "RCP";
        struct.culvert_diameter_mm = 450;
        struct.culvert_invert_level_m_ahd = invertAHD + 0.1;
        struct.culvert_length_m = 10.0;
        struct.culvert_slope = 0.01;
        struct.culvert_count = 1;
      } else if (type === "grated_pit") {
        struct.pit_inlet_level_m_ahd = surfaceAHD - 0.3;
        struct.pit_length_m = 0.6;
        struct.pit_width_m = 0.6;
        struct.pit_opening_ratio = 0.5;
      }
      basimStructures.push(struct);
      renderStructuresList();
      if (typeof updateSceneFromInputs === "function") updateSceneFromInputs();
    }

    function removeStructure(idx) {
      basimStructures.splice(idx, 1);
      renderStructuresList();
      if (typeof updateSceneFromInputs === "function") updateSceneFromInputs();
    }

    function updateStructureField(idx, field, value) {
      if (!basimStructures[idx]) return;
      const numFields = [
        "weir_crest_level_m_ahd", "weir_length_m",
        "culvert_diameter_mm", "culvert_invert_level_m_ahd", "culvert_length_m", "culvert_slope", "culvert_count",
        "culvert_width_mm", "culvert_height_mm",
        "pit_inlet_level_m_ahd", "pit_length_m", "pit_width_m", "pit_opening_ratio",
      ];
      basimStructures[idx][field] = numFields.includes(field) ? parseFloat(value) : value;
      if (typeof updateSceneFromInputs === "function") updateSceneFromInputs();
    }

    function renderStructuresList() {
      const container = document.getElementById("structures-list");
      if (!container) return;
      if (basimStructures.length === 0) {
        container.innerHTML = '<p style="font-size:.75rem;color:var(--muted);margin-top:.4rem">No structures added yet.</p>';
        return;
      }
      let html = "";
      basimStructures.forEach((s, i) => {
        let fields = "";
        if (s.type === "weir") {
          fields = `
            <div class="row"><div class="field"><label>Crest Level (m AHD)</label><input type="number" value="${s.weir_crest_level_m_ahd||''}" step="0.1" onchange="updateStructureField(${i},'weir_crest_level_m_ahd',this.value)"/></div>
            <div class="field"><label>Length (m)</label><input type="number" value="${s.weir_length_m||''}" step="0.1" min="0.1" onchange="updateStructureField(${i},'weir_length_m',this.value)"/></div>
            <div class="field"><label>Lining</label><select onchange="updateStructureField(${i},'weir_lining',this.value)"><option value="bare_earth"${s.weir_lining==='bare_earth'?' selected':''}>Bare Earth</option><option value="concrete"${s.weir_lining==='concrete'?' selected':''}>Concrete</option><option value="rock_lined"${s.weir_lining==='rock_lined'?' selected':''}>Rock Lined</option></select></div></div>`;
        } else if (s.type === "culvert") {
          const isRCBC = s.culvert_material === 'RCBC';
          fields = `
            <div class="row"><div class="field"><label>Material</label><select onchange="updateStructureField(${i},'culvert_material',this.value)"><option value="RCP"${s.culvert_material==='RCP'?' selected':''}>RCP</option><option value="PVC"${s.culvert_material==='PVC'?' selected':''}>PVC</option><option value="CSP"${s.culvert_material==='CSP'?' selected':''}>CSP</option><option value="RCBC"${s.culvert_material==='RCBC'?' selected':''}>RCBC</option></select></div>
            <div class="field" style="${isRCBC?'':'display:none'}"><label>Width (mm)</label><input type="number" value="${s.culvert_width_mm||600}" step="50" onchange="updateStructureField(${i},'culvert_width_mm',this.value)"/></div>
            <div class="field" style="${isRCBC?'':'display:none'}"><label>Height (mm)</label><input type="number" value="${s.culvert_height_mm||450}" step="50" onchange="updateStructureField(${i},'culvert_height_mm',this.value)"/></div>
            <div class="field" style="${isRCBC?'display:none':''}"><label>Diameter (mm)</label><input type="number" value="${s.culvert_diameter_mm||450}" step="25" onchange="updateStructureField(${i},'culvert_diameter_mm',this.value)"/></div>
            <div class="field"><label>Invert (m AHD)</label><input type="number" value="${s.culvert_invert_level_m_ahd||''}" step="0.1" onchange="updateStructureField(${i},'culvert_invert_level_m_ahd',this.value)"/></div></div>
            <div class="row"><div class="field"><label>Length (m)</label><input type="number" value="${s.culvert_length_m||10}" step="0.5" min="1" onchange="updateStructureField(${i},'culvert_length_m',this.value)"/></div>
            <div class="field"><label>Slope (m/m)</label><input type="number" value="${s.culvert_slope||0}" step="0.001" min="0" onchange="updateStructureField(${i},'culvert_slope',this.value)"/></div>
            <div class="field"><label>Barrels</label><input type="number" value="${s.culvert_count||1}" step="1" min="1" onchange="updateStructureField(${i},'culvert_count',this.value)"/></div></div>`;
        } else if (s.type === "grated_pit") {
          fields = `
            <div class="row"><div class="field"><label>Inlet Level (m AHD)</label><input type="number" value="${s.pit_inlet_level_m_ahd||''}" step="0.1" onchange="updateStructureField(${i},'pit_inlet_level_m_ahd',this.value)"/></div>
            <div class="field"><label>Length (m)</label><input type="number" value="${s.pit_length_m||0.6}" step="0.1" min="0.1" onchange="updateStructureField(${i},'pit_length_m',this.value)"/></div>
            <div class="field"><label>Width (m)</label><input type="number" value="${s.pit_width_m||0.6}" step="0.1" min="0.1" onchange="updateStructureField(${i},'pit_width_m',this.value)"/></div></div>
            <div class="row"><div class="field"><label>Opening Ratio (0-1)</label><input type="number" value="${s.pit_opening_ratio||0.5}" step="0.05" min="0.01" max="1" onchange="updateStructureField(${i},'pit_opening_ratio',this.value)"/></div></div>`;
        }
        html += `<div style="border:1px solid #e2e8f0;border-radius:6px;padding:.6rem;margin-bottom:.5rem">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.4rem">
            <strong style="font-size:.82rem">${s.name}</strong>
            <button class="btn btn-outline btn-sm" style="color:#ef4444;border-color:#fca5a5" onclick="removeStructure(${i})">Remove</button>
          </div>${fields}</div>`;
      });
      container.innerHTML = html;
    }

    function getStructuresForRequest() {
      const enabled = document.getElementById("inp-structures-enabled");
      if (!enabled || !enabled.checked) return [];
      return basimStructures.map(s => ({ ...s }));
    }

    function updateResultTabLabels(type) {
      // Hardcoded to basin in HTML
    }

    function setBasinAdvancedInputEnabled(isEnabled) {
      const ids = ["inp-basin-deficit", "inp-basin-suction", "inp-basin-specific-yield"];
      ids.forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.disabled = !isEnabled;
      });
    }

    function updateBasinCloggedInputs() {
      const useClogged = document.getElementById("inp-basin-use-clogged");
      const kInput = document.getElementById("inp-basin-clogged-k");
      const zInput = document.getElementById("inp-basin-clogged-thickness");
      if (!useClogged || !kInput || !zInput) return;
      const enabled = !!useClogged.checked;
      kInput.disabled = !enabled;
      zInput.disabled = !enabled;
    }

    function applyBasinSoilDefaults(profileName) {
      const defaults = BASIN_SOIL_DEFAULTS[profileName] || BASIN_SOIL_DEFAULTS["Sand"];
      const profileFromApi = basinSoilProfiles[profileName] || null;

      const deficitInput = document.getElementById("inp-basin-deficit");
      const suctionInput = document.getElementById("inp-basin-suction");
      const specificYieldInput = document.getElementById("inp-basin-specific-yield");

      if (deficitInput) deficitInput.value = String(defaults.deficit);
      if (suctionInput) suctionInput.value = String(defaults.suction);
      if (specificYieldInput) {
        const sy = profileFromApi && Number.isFinite(profileFromApi.specific_yield)
          ? profileFromApi.specific_yield
          : defaults.specificYield;
        specificYieldInput.value = String(sy);
      }
    }

    function updateBasinAdvancedMode() {
      const modeSelect = document.getElementById("inp-basin-param-mode");
      const profileSelect = document.getElementById("inp-basin-soil-profile");
      const note = document.getElementById("basin-default-note");
      if (!modeSelect || !profileSelect) return;

      const isCustom = modeSelect.value === "custom";
      setBasinAdvancedInputEnabled(isCustom);

      if (note) {
        note.textContent = isCustom
          ? "Custom mode enabled. Enter project-specific Green-Ampt/Hantush values below."
          : "Using soil-type defaults. Switch to \"Specify custom values\" to edit manually.";
      }

      if (!isCustom) {
        applyBasinSoilDefaults(profileSelect.value);
      }
    }

    async function loadBasinSoilProfiles() {
      const profileSelect = document.getElementById("inp-basin-soil-profile");
      if (!profileSelect) return;

      const previousValue = profileSelect.value || "Sand";
      try {
        const resp = await fetch(apiUrl("/api/soil-profiles"));
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const profiles = await resp.json();
        basinSoilProfiles = {};

        if (Array.isArray(profiles) && profiles.length > 0) {
          profileSelect.innerHTML = "";
          profiles.forEach((p) => {
            basinSoilProfiles[p.name] = p;
            const option = document.createElement("option");
            option.value = p.name;
            option.textContent = p.name;
            profileSelect.appendChild(option);
          });
        }
      } catch (err) {
        console.warn("Failed to load basin soil profile defaults", err);
      }

      const optionValues = Array.from(profileSelect.options).map((opt) => opt.value);
      profileSelect.value = optionValues.includes(previousValue) ? previousValue : (optionValues[0] || "Sand");
      updateBasinAdvancedMode();
    }

    // ── Map setup ───────────────────────────────────────────────────────────
    const map = L.map("map").setView([-31.9505, 115.8605], 11);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(map);

    let marker = L.marker([-31.9505, 115.8605], { draggable: true }).addTo(map);

    marker.on("dragend", () => {
      if (resultsLocked) { marker.setLatLng([parseFloat(document.getElementById("inp-lat").value), parseFloat(document.getElementById("inp-lng").value)]); return; }
      const { lat, lng } = marker.getLatLng();
      document.getElementById("inp-lat").value = lat.toFixed(5);
      document.getElementById("inp-lng").value = lng.toFixed(5);
      updateLgaWarning();
    });

    map.on("click", (e) => {
      if (resultsLocked) return;
      marker.setLatLng(e.latlng);
      document.getElementById("inp-lat").value = e.latlng.lat.toFixed(5);
      document.getElementById("inp-lng").value = e.latlng.lng.toFixed(5);
      updateLgaWarning();
    });

    document.getElementById("inp-basin-soil-profile").addEventListener("change", () => {
      const mode = document.getElementById("inp-basin-param-mode").value;
      if (mode !== "custom") {
        applyBasinSoilDefaults(document.getElementById("inp-basin-soil-profile").value);
      }
    });
    document.getElementById("inp-basin-param-mode").addEventListener("change", updateBasinAdvancedMode);
    const useCloggedEl = document.getElementById("inp-basin-use-clogged");
    if (useCloggedEl) useCloggedEl.addEventListener("change", updateBasinCloggedInputs);

    loadBasinSoilProfiles();
    updateBasinAdvancedMode();
    updateBasinCloggedInputs();
    updateClimateControls();

    const climateScenarioEl = document.getElementById("inp-cc-scenario");
    if (climateScenarioEl) {
      climateScenarioEl.addEventListener("change", updateClimateControls);
    }

    // Sync manual coord input → map
    ["inp-lat", "inp-lng"].forEach((id) => {
      document.getElementById(id).addEventListener("change", () => {
        const lat = parseFloat(document.getElementById("inp-lat").value);
        const lng = parseFloat(document.getElementById("inp-lng").value);
        if (!isNaN(lat) && !isNaN(lng)) {
          marker.setLatLng([lat, lng]);
          map.panTo([lat, lng]);
          updateLgaWarning();
        }
      });
    });

    // ── Catchment management ────────────────────────────────────────────────
    var catchments = [
      {
        name: "Roof",
        area_ha: 0.05,
        slope: 0.01,
        paved_fraction: 0.95,
        supplementary_fraction: 0.0,
        grassed_fraction: 0.05,
        soil_type: 2,
        amc: 2,
        paved_additional_time_minutes: 0,
        supplementary_additional_time_minutes: 0,
        grassed_additional_time_minutes: 0,
        paved_flow_path_length_m: 15,
        supplementary_flow_path_length_m: 10,
        grassed_flow_path_length_m: 20,
        paved_flow_path_slope_pct: 1,
        supplementary_flow_path_slope_pct: 2,
        grassed_flow_path_slope_pct: 2,
        paved_n_star: 0.011,
        supplementary_n_star: 0.013,
        grassed_n_star: 0.25,
        paved_depression_storage_mm: 1.0,
        supplementary_depression_storage_mm: 1.0,
        grassed_depression_storage_mm: 5.0,
      },
    ];

    function renderCatchments() {
      const list = document.getElementById("catchments-list");
      list.innerHTML = "";
      catchments.forEach((c, i) => {
        const div = document.createElement("div");
        div.className = "catchment-entry";
        div.innerHTML = `
          ${catchments.length > 1 ? `<button class=\"remove-catch\" onclick=\"removeCatchment(${i})\">&times;</button>` : ""}
          <div class="row">
            <div class="field"><label>Name</label><input value="${c.name}" onchange="catchments[${i}].name=this.value" /></div>
            <div class="field"><label>Area (ha)</label><input type="number" value="${c.area_ha}" step="0.001" min="0.001" onchange="catchments[${i}].area_ha=+this.value" /></div>
          </div>
          <div class="row">
            <div class="field"><label>Slope</label><input type="number" value="${c.slope}" step="0.001" min="0.001" onchange="catchments[${i}].slope=+this.value" /></div>
          </div>
          <details style="margin-top:.3rem">
            <summary style="font-size:.78rem;cursor:pointer;color:var(--primary)">Surface fractions &amp; ILSAX parameters</summary>
            <div class="row" style="margin-top:.3rem">
              <div class="field"><label>Paved (DCIA)</label><input type="number" value="${c.paved_fraction}" step="0.05" min="0" max="1" onchange="catchments[${i}].paved_fraction=+this.value" /></div>
              <div class="field"><label>Supplementary</label><input type="number" value="${c.supplementary_fraction}" step="0.05" min="0" max="1" onchange="catchments[${i}].supplementary_fraction=+this.value" /></div>
              <div class="field"><label>Grassed</label><input type="number" value="${c.grassed_fraction}" step="0.05" min="0" max="1" onchange="catchments[${i}].grassed_fraction=+this.value" /></div>
            </div>
            <div class="row">
              <div class="field"><label>Soil type (1–4)</label>
                <select onchange="catchments[${i}].soil_type=+this.value">
                  <option value="1" ${c.soil_type==1?'selected':''}>1 — A (sandy)</option>
                  <option value="2" ${c.soil_type==2?'selected':''}>2 — B (sandy loam)</option>
                  <option value="3" ${c.soil_type==3?'selected':''}>3 — C (loam/clay)</option>
                  <option value="4" ${c.soil_type==4?'selected':''}>4 — D (clay)</option>
                </select>
              </div>
              <div class="field"><label>AMC (1–4)</label>
                <select onchange="catchments[${i}].amc=+this.value">
                  <option value="1" ${c.amc==1?'selected':''}>1 — Dry</option>
                  <option value="2" ${c.amc==2?'selected':''}>2 — Rather dry</option>
                  <option value="3" ${c.amc==3?'selected':''}>3 — Rather wet</option>
                  <option value="4" ${c.amc==4?'selected':''}>4 — Saturated</option>
                </select>
              </div>
            </div>
            <p style="font-size:.72rem;margin:.4rem 0 .2rem;color:#666;font-weight:600">Flow Path Parameters (Kinematic Wave — DRAINS Eq. 8.3)</p>
            <table style="width:100%;font-size:.72rem;border-collapse:collapse;margin-bottom:.3rem">
              <thead><tr style="text-align:left">
                <th style="padding:2px 4px"></th>
                <th style="padding:2px 4px">Paved</th>
                <th style="padding:2px 4px">Supplementary</th>
                <th style="padding:2px 4px">Grassed</th>
              </tr></thead>
              <tbody>
                <tr><td style="padding:2px 4px">Additional time (min)</td>
                  <td style="padding:2px"><input type="number" value="${c.paved_additional_time_minutes}" step="1" min="0" style="width:60px" onchange="catchments[${i}].paved_additional_time_minutes=+this.value" /></td>
                  <td style="padding:2px"><input type="number" value="${c.supplementary_additional_time_minutes}" step="1" min="0" style="width:60px" onchange="catchments[${i}].supplementary_additional_time_minutes=+this.value" /></td>
                  <td style="padding:2px"><input type="number" value="${c.grassed_additional_time_minutes}" step="1" min="0" style="width:60px" onchange="catchments[${i}].grassed_additional_time_minutes=+this.value" /></td>
                </tr>
                <tr><td style="padding:2px 4px">Flow path length (m)</td>
                  <td style="padding:2px"><input type="number" value="${c.paved_flow_path_length_m}" step="1" min="0" style="width:60px" onchange="catchments[${i}].paved_flow_path_length_m=+this.value" /></td>
                  <td style="padding:2px"><input type="number" value="${c.supplementary_flow_path_length_m}" step="1" min="0" style="width:60px" onchange="catchments[${i}].supplementary_flow_path_length_m=+this.value" /></td>
                  <td style="padding:2px"><input type="number" value="${c.grassed_flow_path_length_m}" step="1" min="0" style="width:60px" onchange="catchments[${i}].grassed_flow_path_length_m=+this.value" /></td>
                </tr>
                <tr><td style="padding:2px 4px">Flow path slope (%)</td>
                  <td style="padding:2px"><input type="number" value="${c.paved_flow_path_slope_pct}" step="0.5" min="0.01" style="width:60px" onchange="catchments[${i}].paved_flow_path_slope_pct=+this.value" /></td>
                  <td style="padding:2px"><input type="number" value="${c.supplementary_flow_path_slope_pct}" step="0.5" min="0.01" style="width:60px" onchange="catchments[${i}].supplementary_flow_path_slope_pct=+this.value" /></td>
                  <td style="padding:2px"><input type="number" value="${c.grassed_flow_path_slope_pct}" step="0.5" min="0.01" style="width:60px" onchange="catchments[${i}].grassed_flow_path_slope_pct=+this.value" /></td>
                </tr>
                <tr><td style="padding:2px 4px">Retardance n*</td>
                  <td style="padding:2px"><input type="number" value="${c.paved_n_star}" step="0.001" min="0.001" style="width:60px" onchange="catchments[${i}].paved_n_star=+this.value" /></td>
                  <td style="padding:2px"><input type="number" value="${c.supplementary_n_star}" step="0.001" min="0.001" style="width:60px" onchange="catchments[${i}].supplementary_n_star=+this.value" /></td>
                  <td style="padding:2px"><input type="number" value="${c.grassed_n_star}" step="0.001" min="0.001" style="width:60px" onchange="catchments[${i}].grassed_n_star=+this.value" /></td>
                </tr>
              </tbody>
            </table>
            <div class="row">
              <div class="field"><label>Paved DS (mm)</label><input type="number" value="${c.paved_depression_storage_mm}" step="0.5" min="0" onchange="catchments[${i}].paved_depression_storage_mm=+this.value" /></div>
              <div class="field"><label>Supp. DS (mm)</label><input type="number" value="${c.supplementary_depression_storage_mm}" step="0.5" min="0" onchange="catchments[${i}].supplementary_depression_storage_mm=+this.value" /></div>
              <div class="field"><label>Grass DS (mm)</label><input type="number" value="${c.grassed_depression_storage_mm}" step="0.5" min="0" onchange="catchments[${i}].grassed_depression_storage_mm=+this.value" /></div>
            </div>
          </details>
        `;
        list.appendChild(div);
      });
    }

    function addCatchment() {
      catchments.push({
        name: `Catchment ${catchments.length + 1}`,
        area_ha: 0.02,
        slope: 0.015,
        paved_fraction: 0.50,
        supplementary_fraction: 0.10,
        grassed_fraction: 0.40,
        soil_type: 2,
        amc: 2,
        paved_additional_time_minutes: 0,
        supplementary_additional_time_minutes: 0,
        grassed_additional_time_minutes: 0,
        paved_flow_path_length_m: 15,
        supplementary_flow_path_length_m: 10,
        grassed_flow_path_length_m: 20,
        paved_flow_path_slope_pct: 1,
        supplementary_flow_path_slope_pct: 2,
        grassed_flow_path_slope_pct: 2,
        paved_n_star: 0.011,
        supplementary_n_star: 0.013,
        grassed_n_star: 0.25,
        paved_depression_storage_mm: 1.0,
        supplementary_depression_storage_mm: 1.0,
        grassed_depression_storage_mm: 5.0,
      });
      renderCatchments();
    }

    function removeCatchment(i) {
      catchments.splice(i, 1);
      renderCatchments();
    }

    renderCatchments();

// ── Tabs ────────────────────────────────────────────────────────────────
document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(btn.dataset.tab).classList.add("active");
  });
});

// ── Chart instances (for cleanup) ───────────────────────────────────────
let chartInstances = [];

function destroyCharts() {
  chartInstances.forEach((c) => c.destroy());
  chartInstances = [];
}

// ── Palette ─────────────────────────────────────────────────────────────
const COLORS = [
  "#1a6b4f", "#f59e0b", "#3b82f6", "#ef4444", "#8b5cf6",
  "#ec4899", "#14b8a6", "#f97316", "#6366f1", "#84cc16",
];

// ── Standard ARR durations (minutes) ────────────────────────────────────
const STANDARD_DURATIONS = [
  10, 15, 20, 25, 30, 45,
  60, 90, 120, 180,
  270, 360, 540, 720, 1080, 1440, 1800,
  2160, 2880, 4320, 5760, 7200, 8640, 10080,
];
const DURATION_LABELS = {
  1:"1 min",2:"2 min",3:"3 min",4:"4 min",5:"5 min",10:"10 min",15:"15 min",
  20:"20 min",25:"25 min",30:"30 min",45:"45 min",60:"1 hr",90:"1.5 hr",
  120:"2 hr",180:"3 hr",270:"4.5 hr",360:"6 hr",540:"9 hr",720:"12 hr",
  1080:"18 hr",1440:"24 hr",1800:"30 hr",2160:"36 hr",2880:"48 hr",
  4320:"72 hr",5760:"96 hr",7200:"120 hr",8640:"144 hr",10080:"168 hr",
};
const DEFAULT_CHECKED = new Set([30, 60]);

function getClimateSelection() {
  const scenarioEl = document.getElementById("inp-cc-scenario");
  const epochEl = document.getElementById("inp-cc-epoch");
  const scenario = scenarioEl ? scenarioEl.value : "Historical";
  const isHistorical = !scenario || scenario === "Historical";
  const epochVal = epochEl ? parseInt(epochEl.value, 10) : NaN;
  return {
    scenario: isHistorical ? null : scenario,
    epoch: isHistorical || Number.isNaN(epochVal) ? null : epochVal,
  };
}

function updateClimateControls() {
  const scenarioEl = document.getElementById("inp-cc-scenario");
  const epochField = document.getElementById("cc-epoch-field");
  const info = document.getElementById("cc-info");
  if (!scenarioEl || !epochField || !info) return;

  const scenario = scenarioEl.value;
  const isHistorical = !scenario || scenario === "Historical";
  epochField.style.display = isHistorical ? "none" : "";
  info.innerHTML = isHistorical
    ? "<em>(i) Historical - only to be used for historical assessments</em>"
    : "<em>(i) ARR climate change factors are applied for the selected SSP and planning horizon year.</em>";
}

function renderDurationGrid() {
  const grid = document.getElementById("duration-grid");
  grid.innerHTML = "";
  STANDARD_DURATIONS.forEach((d) => {
    const lbl = document.createElement("label");
    lbl.className = "dur-check";
    lbl.innerHTML = `<input type="checkbox" value="${d}" ${DEFAULT_CHECKED.has(d)?"checked":""}><span>${DURATION_LABELS[d]}</span>`;
    grid.appendChild(lbl);
  });
}
renderDurationGrid();

function toggleAllDurations() {
  const boxes = document.querySelectorAll("#duration-grid input[type=checkbox]");
  const allChecked = Array.from(boxes).every((b) => b.checked);
  boxes.forEach((b) => (b.checked = !allChecked));
}

function getSelectedDurations() {
  return Array.from(document.querySelectorAll("#duration-grid input[type=checkbox]:checked"))
    .map((b) => parseInt(b.value));
}

const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

async function submitAnalysis(path, payload, onEvent) {
  const submissionResponse = await fetch(apiUrl(path), {
    method: "POST",
    headers: await authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
  if (!submissionResponse.ok) {
    const error = await submissionResponse.json().catch(() => ({ detail: submissionResponse.statusText }));
    throw new Error(error.detail || JSON.stringify(error));
  }

  const submission = await submissionResponse.json();
  let eventCursor = 0;
  while (true) {
    const eventResponse = await fetch(
      apiUrl(`/api/jobs/${submission.job_id}/events?after=${eventCursor}`),
      { headers: await authHeaders() },
    );
    if (eventResponse.ok) {
      const eventPage = await eventResponse.json();
      eventCursor = eventPage.next;
      for (const event of eventPage.events) onEvent?.(event);
    }

    const statusResponse = await fetch(apiUrl(`/api/jobs/${submission.job_id}`), {
      headers: await authHeaders(),
    });
    if (!statusResponse.ok) throw new Error("Unable to retrieve analysis status.");
    const job = await statusResponse.json();
    if (job.status === "completed") {
      const resultResponse = await fetch(apiUrl(`/api/jobs/${submission.job_id}/result`), {
        headers: await authHeaders(),
      });
      if (!resultResponse.ok) throw new Error("Analysis completed but its result is unavailable.");
      return resultResponse.json();
    }
    if (job.status === "failed" || job.status === "cancelled") {
      throw new Error(job.error || `Analysis ${job.status}.`);
    }
    await wait(1000);
  }
}

// ── Run simulation ──────────────────────────────────────────────────────
async function runSimulation() {


  const btn = document.getElementById("btn-run");
  const loading = document.getElementById("loading");
  btn.disabled = true;
  loading.classList.add("active");

  const aepSelect = document.getElementById("inp-aeps");
  const selectedAEPs = Array.from(aepSelect.selectedOptions).map((o) => parseFloat(o.value));
  const durations = getSelectedDurations();
  // Design AEP = smallest selected AEP (most rare); pattern rank = median (4)
  const designAep = Math.min(...selectedAEPs);

  const selectedStructureType = getStructureType();
  const basinBaseLength = parseFloat(document.getElementById("inp-basin-length").value);
  const basinBaseWidth = parseFloat(document.getElementById("inp-basin-width").value);
  const basinSideSlope = parseFloat(document.getElementById("inp-basin-side-slope").value);
  const basinMaxDepth = parseFloat(document.getElementById("inp-basin-depth").value);
  const initialMoistureDeficit = parseFloat(document.getElementById("inp-basin-deficit").value);
  const capillarySuctionHead = parseFloat(document.getElementById("inp-basin-suction").value);
  const specificYield = parseFloat(document.getElementById("inp-basin-specific-yield").value);

  // Collect hydraulic structures (if enabled)
  const hydraulicStructures = getStructuresForRequest();


  const isShallowGW = false;
  const climate = getClimateSelection();

  const body = {
    project_code: document.getElementById("inp-project-code").value.trim() || null,
    latitude: parseFloat(document.getElementById("inp-lat").value),
    longitude: parseFloat(document.getElementById("inp-lng").value),
    catchments: catchments,
    aep_percentages: selectedAEPs,
    durations_minutes: durations,
    vertical_k_mm_per_hr: parseFloat(document.getElementById("inp-kv").value) * 1000 / 24,
    horizontal_k_mm_per_hr: document.getElementById("inp-kh").value ? parseFloat(document.getElementById("inp-kh").value) * 1000 / 24 : null,
    design_drain_time_hours: 24,
    soil_moderation_factor: parseFloat(document.getElementById("inp-safety").value),
    surface_level_m_ahd: parseFloat(document.getElementById("inp-surface-lvl").value),
    design_gwl_m_ahd: parseFloat(document.getElementById("inp-design-gwl").value),
    base_aquifer_level_m_ahd: parseFloat(document.getElementById("inp-base-aquifer-lvl").value),
    pattern_rank: 4,
    design_aep_percent: designAep,
    basin_base_length_m: parseFloat(document.getElementById("inp-basin-length").value),
    basin_base_width_m: parseFloat(document.getElementById("inp-basin-width").value),
    basin_side_slope_ratio: parseFloat(document.getElementById("inp-basin-side-slope").value),
    basin_max_depth_m: parseFloat(document.getElementById("inp-basin-depth").value),
    initial_moisture_deficit: parseFloat(document.getElementById("inp-basin-deficit").value),
    capillary_suction_head_m: parseFloat(document.getElementById("inp-basin-suction").value),
    specific_yield: parseFloat(document.getElementById("inp-basin-specific-yield").value),
    basin_side_infil_enabled: !!document.getElementById("inp-basin-side-infil")?.checked,
    basin_use_clogged_layer: !!document.getElementById("inp-basin-use-clogged")?.checked,
    basin_clogged_k_m_per_day: parseFloat(document.getElementById("inp-basin-clogged-k")?.value || 0.1),
    basin_clogged_thickness_m: parseFloat(document.getElementById("inp-basin-clogged-thickness")?.value || 0.1),
    hydraulic_structures: hydraulicStructures,
    use_live_data: true,
    climate_scenario: climate.scenario,
    climate_epoch: climate.epoch,
  };

  // Keep the exact design request so the clogging assessment can reuse it
  // (year 0 must reproduce this unclogged run exactly).
  lastSimRequest = body;

  // Show progress panel with a progress bar based on number of runs complete
  const isRoldinRun = true;
  const progressPanel = document.getElementById("simulation-progress");
  const progressBar = document.getElementById("progress-bar");
  const progressCurrent = document.getElementById("progress-current-storm");
  const progressList = document.getElementById("progress-storm-list");
  if (isRoldinRun) {
    progressPanel.style.display = "";
    document.getElementById("placeholder").style.display = "none";
    progressBar.style.width = "0%";
    progressCurrent.textContent = "Starting...";
    progressList.innerHTML = "";
  }

  try {
    const resultData = await submitAnalysis("/api/analyses/design", body, (event) => {
      if (event.type !== "progress" || !isRoldinRun) return;
      const pct = event.total > 0 ? Math.round((event.step / event.total) * 100) : event.progress;
      progressBar.style.width = pct + "%";
      if (event.done) {
        progressCurrent.textContent = `\u2713 ${event.storm}`;
        const row = document.createElement("div");
        row.textContent = `\u2713  ${event.storm}`;
        row.style.color = "#16a34a";
        progressList.appendChild(row);
        progressList.scrollTop = progressList.scrollHeight;
      } else if (event.storm) {
        progressCurrent.textContent = `\u25b6 ${event.storm}`;
      }
    });
    progressPanel.style.display = "none";
    renderResults(resultData);
  } catch (e) {
    progressPanel.style.display = "none";
    alert("Simulation failed:\n" + e.message);
  } finally {
    btn.disabled = false;
    loading.classList.remove("active");
  }
}

// ── Render warnings (pooling / overtopping) ────────────────────────────
function renderWarnings(warnings) {
  let banner = document.getElementById("warnings-banner");
  if (!banner) {
    banner = document.createElement("div");
    banner.id = "warnings-banner";
    banner.style.cssText = "margin:.5rem 0 1rem;padding:.75rem 1rem;border-radius:6px;font-size:.82rem;display:none";
    const rc = document.getElementById("results-container");
    if (rc) rc.insertBefore(banner, rc.firstChild);
  }
  banner.innerHTML = "";
  if (!warnings || !warnings.length) {
    banner.style.display = "none";
    return;
  }
  banner.style.background = "#fef3c7";
  banner.style.border = "1px solid #f59e0b";
  banner.style.color = "#92400e";
  const title = document.createElement("div");
  title.style.fontWeight = "700";
  title.style.marginBottom = ".35rem";
  title.textContent = "⚠ Basin Overtopping / Pooling";
  banner.appendChild(title);
  // First entry is the summary; the rest are per-storm detail lines.
  const summary = document.createElement("div");
  summary.style.marginBottom = ".35rem";
  summary.textContent = warnings[0];
  banner.appendChild(summary);
  if (warnings.length > 1) {
    const details = document.createElement("details");
    const s = document.createElement("summary");
    s.textContent = `${warnings.length - 1} overtopping event(s) — show details`;
    s.style.cursor = "pointer";
    details.appendChild(s);
    const list = document.createElement("ul");
    list.style.margin = ".35rem 0 0 1.2rem";
    list.style.padding = "0";
    for (let i = 1; i < warnings.length; i++) {
      const li = document.createElement("li");
      li.style.marginBottom = ".15rem";
      li.textContent = warnings[i];
      list.appendChild(li);
    }
    details.appendChild(list);
    banner.appendChild(details);
  }
  banner.style.display = "block";
}

// ── Render results ───────────────────────────────────────────────────────
function renderResults(data) {
  simulationData = data;
  const resultStructureType = data.structure_type || getStructureType();
  const isBasin = resultStructureType === "basin";
  const structureLabel = getStructureLabel(resultStructureType);
  updateResultTabLabels(resultStructureType);
  document.getElementById("placeholder").style.display = "none";
  document.getElementById("results-container").style.display = "block";
  destroyCharts();

  // ── Warnings banner (pooling / overtopping) ───
  renderWarnings(data.warnings);

  // ── Design summary ───
  const ds = document.getElementById("design-summary");

  // Climate scenario badge
  const ccLabel = data.climate_scenario_label || "Historical";
  const isHistorical = ccLabel === "Historical";
  const ccBadgeColor = isHistorical ? "#6b7280" : "#2563eb";
  const ccBadgeHTML = `<div style="margin-bottom:.5rem;font-size:.8rem;font-weight:600;color:${ccBadgeColor}">
    Climate Scenario: ${ccLabel}${isHistorical ? ' <span style=\"font-weight:400;color:#9ca3af\">(unadjusted)</span>' : ''}
  </div>`;

  if (data.soakwell_design) {
    const d = data.soakwell_design;
    const modelName = data.selected_model || (data.soakwell_timeseries ? data.soakwell_timeseries.selected_model : "standard");
    const modelReason = data.model_selection_reason || (data.soakwell_timeseries ? data.soakwell_timeseries.model_selection_reason : "");
    let configHTML = "";
    for (const [name, count] of Object.entries(d.configuration)) {
      configHTML += `<span class="config-tag">${count} × ${name}</span>`;
    }
    // Check for spill
    const spilled = data.soakwell_timeseries && data.soakwell_timeseries.spill_flag && data.soakwell_timeseries.spill_flag.some(f => f);
    const spillBadge = spilled
      ? `<div class="metric-card" style="border-color:#fca5a5;background:#fef2f2"><div class="value" style="color:#dc2626">SPILL</div><div class="label" style="color:#991b1b">${structureLabel} Overflows</div></div>`
      : `<div class="metric-card" style="border-color:#86efac;background:#f0fdf4"><div class="value" style="color:#166534">OK</div><div class="label" style="color:#166534">No Overflow</div></div>`;
    const configTitle = isBasin ? "Basin Geometry" : "Soakwell Configuration";
    let configBlock = `<h4 style="margin-top:1rem;font-size:.85rem;color:var(--primary)">${configTitle}</h4><div class="config-list">`;
    if (isBasin && data.basin_geometry) {
      configBlock += `
        <span class="config-tag">L = ${data.basin_geometry.base_length_m} m</span>
        <span class="config-tag">W = ${data.basin_geometry.base_width_m} m</span>
        <span class="config-tag">Slope 1:${data.basin_geometry.side_slope_ratio}</span>
        <span class="config-tag">Max depth = ${data.basin_geometry.max_depth_m} m</span>
      `;
      if (data.basin_geometry.use_clogged_layer) {
        configBlock += `
          <span class="config-tag">Clogged layer ON</span>
          <span class="config-tag">Kc = ${Number(data.basin_geometry.clogged_k_m_per_day || 0).toFixed(3)} m/day</span>
          <span class="config-tag">zc = ${Number(data.basin_geometry.clogged_thickness_m || 0).toFixed(3)} m</span>
        `;
      }
    } else {
      configBlock += configHTML;
    }
    configBlock += `</div>`;

    ds.innerHTML = `
      ${ccBadgeHTML}
      <div style="margin-bottom:.5rem;font-size:.8rem;color:#374151">
        Routing model: <strong>${modelName}</strong>
        ${modelReason ? `<div style="margin-top:.2rem;color:#6b7280">${modelReason}</div>` : ""}
      </div>
      <div class="design-grid" style="margin-top:.8rem">
        <div class="metric-card">
          <div class="value">${d.required_storage_m3.toFixed(2)}</div>
          <div class="label">Required ${structureLabel} Storage (m³)</div>
        </div>
        <div class="metric-card">
          <div class="value">${d.residual_storage_m3.toFixed(2)}</div>
          <div class="label">Residual Storage (m³)</div>
        </div>
        <div class="metric-card">
          <div class="value">${d.critical_duration_minutes}</div>
          <div class="label">Critical Duration (min)</div>
        </div>
        <div class="metric-card">
          <div class="value">${d.drain_time_hours.toFixed(1)}</div>
          <div class="label">Drain Time (hrs)</div>
        </div>
        <div class="metric-card">
          <div class="value">${d.infiltration_shortfall_m3.toFixed(2)}</div>
          <div class="label">Infiltration Shortfall (m³)</div>
        </div>
        <div class="metric-card">
          <div class="value">${d.aep}</div>
          <div class="label">Design AEP</div>
        </div>
        ${spillBadge}
      </div>
      ${configBlock}
    `;
  } else {
    ds.innerHTML = `${ccBadgeHTML}<p style="color:var(--muted);padding:1rem">No ${structureLabel.toLowerCase()} design available.</p>`;
  }



  // ── Runoff table ───
  const tbody = document.querySelector("#runoff-table tbody");
  tbody.innerHTML = "";
  for (const row of data.runoff_table) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${row.aep}</td>
      <td>${row.duration_minutes}</td>
      <td>${row.pattern_rank}</td>
      <td>${row.peak_discharge_cms.toFixed(4)}</td>
      <td>${row.runoff_volume_m3.toFixed(2)}</td>
      <td>${row.time_to_peak_minutes.toFixed(1)}</td>
    `;
    tbody.appendChild(tr);
  }

  // ── Results Summary Table ───
  const resultsTbody = document.querySelector("#table-results-summary tbody");
  if (resultsTbody) {
    resultsTbody.innerHTML = "";
    if (data.model_runs && data.model_runs.length > 0) {
      const run = data.model_runs[0];

      const renderRow = (eventLabel, summary) => {
        const tr = document.createElement("tr");
        const dur = summary.critical_duration_minutes || 0;
        const rank = summary.critical_pattern_rank || 0;
        const vol = summary.max_storage_m3 || 0;
        const dep = summary.peak_depth_m || 0;
        const mound = summary.peak_mound_height_m || 0;
        const spillVol = summary.total_overflow_m3 || 0;
        tr.innerHTML = `
          <td><strong>${eventLabel}</strong></td>
          <td>${dur} min (Rank ${rank})</td>
          <td>${vol.toFixed(2)}</td>
          <td>${dep.toFixed(3)}</td>
          <td>${mound.toFixed(3)}</td>
          <td style="color:${summary.spilled ? '#dc2626;font-weight:600' : '#166534'}">${summary.spilled ? 'Yes' : 'No'}</td>
          <td>${spillVol.toFixed(2)}</td>
        `;
        resultsTbody.appendChild(tr);
      };

      if (run.depth_summary) renderRow("Critical Peak Depth", run.depth_summary);
      if (run.drawdown_summary) renderRow("Critical Drawdown Time", run.drawdown_summary);
    } else {
      resultsTbody.innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--muted)">No results data.</td></tr>`;
    }
  }

  // Hook into canvas graphic renderer
  if (typeof renderBasinGraphic === "function") {
    renderBasinGraphic();
  }

  // Update the 2D section/plan with results (peak water level + peak mound)
  if (typeof renderResults3D === "function") {
    renderResults3D(data);
  }

  // ── Median ponded depth per duration (Results Summary graph) ───
  renderMedianDepthChart(data);

  // ── Cumulative volume charts ───
  renderCumulativeVolumeCharts(data.hydrographs);

  // ── Results Dashboard ───
  if (resultStructureType === "basin") {
    document.getElementById("btn-tab-clogging").style.display = "";
    document.getElementById("btn-run-clogging").style.display = "";
    initResultsDashboard(data);
  } else {
    document.getElementById("btn-tab-clogging").style.display = "none";
    document.getElementById("btn-run-clogging").style.display = "none";
    document.getElementById("dashboard-duration-select").style.display = "none";
    renderSoakwellPerformanceChart(data.soakwell_timeseries, data.soakwell_design, resultStructureType);
  }

  // Lock the design inputs — the user must save and/or clear the results
  // before changing parameters and re-running.
  setInputsLocked(true);
}

// ── Results lock / clear ─────────────────────────────────────────────────
// After a run the design inputs are frozen so the on-screen results always
// match the inputs shown. The user clears (or saves) results to edit + re-run.
function setInputsLocked(locked) {
  resultsLocked = locked;
  const sidebar = document.getElementById("sidebar");
  if (sidebar) {
    sidebar.querySelectorAll("input, select, textarea, button").forEach((el) => {
      el.disabled = locked;
    });
    sidebar.classList.toggle("inputs-locked", locked);
  }
  const lockBar = document.getElementById("results-lock-bar");
  if (lockBar) lockBar.style.display = locked ? "flex" : "none";
}

function clearResults() {
  if (simulationData && !confirm(
    "Clear the current results and unlock the design inputs?\n\n" +
    "Make sure you have saved a report first if you need a record — this cannot be undone."
  )) {
    return;
  }
  simulationData = null;
  lastSimRequest = null;
  cloggingTimelineData = null;
  // Hide results, restore the pre-run placeholder.
  document.getElementById("results-container").style.display = "none";
  const ph = document.getElementById("placeholder");
  if (ph) ph.style.display = "";
  // Reset the 2D preview back to live design mode.
  if (typeof setDesign2D === "function") setDesign2D();
  // Unlock the inputs.
  setInputsLocked(false);
}

let dashboardChartInstance = null;
let dashboardSecondaryChartInstance = null;
let dashboardCloggingChartInstance = null;
let clogYearDepthChartInstance = null;
let clogYearDrawdownChartInstance = null;
let medianDepthChartInstance = null;
let cloggingTimelineData = null;   // full CloggingAnalysisResponse, kept for row-click lookups
let cloggingSelectedYearRow = null;

/**
 * Compute the median peak ponded depth (across temporal patterns) for each
 * storm duration. Returns { durations:[min], medians:[m], allowable:m }.
 */
function computeMedianDepthByDuration(data) {
    const out = { durations: [], medians: [], allowable: 0 };
    if (!data || !data.basin_routing_depths) return out;
    out.allowable = parseFloat(document.getElementById("inp-basin-depth").value) || 1.2;
    const durations = Object.keys(data.basin_routing_depths).map(Number).sort((a, b) => a - b);
    durations.forEach((dur) => {
        const byPattern = data.basin_routing_depths[dur];
        if (!byPattern) return;
        const peaks = [];
        for (const depths of Object.values(byPattern)) {
            if (depths && depths.length) peaks.push(Math.max(...depths));
        }
        if (!peaks.length) return;
        peaks.sort((a, b) => a - b);
        const mid = Math.floor(peaks.length / 2);
        const median = peaks.length % 2 ? peaks[mid] : (peaks[mid - 1] + peaks[mid]) / 2;
        out.durations.push(dur);
        out.medians.push(median);
    });
    return out;
}

/**
 * Render the "median ponded depth per duration" bar chart in the Results
 * Summary block (Design tab). Bars exceeding the allowable depth turn red.
 */
function renderMedianDepthChart(data) {
    const canvas = document.getElementById("median-depth-chart");
    if (!canvas) return;
    const stats = computeMedianDepthByDuration(data);
    if (!stats.durations.length) {
        if (medianDepthChartInstance) { medianDepthChartInstance.destroy(); medianDepthChartInstance = null; }
        return;
    }
    const labels = stats.durations.map((d) => d + " min");
    const colors = stats.medians.map((m) =>
        m > stats.allowable ? "rgba(220,38,38,0.75)" : "rgba(26,107,79,0.75)");
    const ctx = canvas.getContext("2d");
    if (medianDepthChartInstance) medianDepthChartInstance.destroy();
    medianDepthChartInstance = new Chart(ctx, {
        type: "bar",
        data: {
            labels: labels,
            datasets: [{
                label: "Median peak ponded depth (m)",
                data: stats.medians,
                backgroundColor: colors,
                borderColor: colors.map((c) => c.replace("0.75", "1")),
                borderWidth: 1,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                title: { display: true, text: "Median Ponded Depth per Duration", font: { size: 14 } },
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (c) => `Median peak: ${c.parsed.y.toFixed(3)} m`,
                    },
                },
                annotation: {
                    annotations: {
                        allowable: {
                            type: "line",
                            yMin: stats.allowable,
                            yMax: stats.allowable,
                            borderColor: "red",
                            borderWidth: 2,
                            borderDash: [5, 5],
                            label: {
                                display: true,
                                content: "Allowable Depth (" + stats.allowable.toFixed(2) + " m)",
                                position: "end",
                            },
                        },
                    },
                },
            },
            scales: {
                x: { title: { display: true, text: "Storm Duration" } },
                y: { title: { display: true, text: "Median Peak Depth (m)" }, min: 0 },
            },
        },
    });
}


function initResultsDashboard(data) {
  const durSelect = document.getElementById("dashboard-duration-select");
  durSelect.style.display = "";
  durSelect.innerHTML = "";

  if (!data.basin_routing_times || Object.keys(data.basin_routing_times).length === 0) {
      console.warn("No routing data for dashboard");
        return;
      }

  // Populate durations dropdown
  const durations = Object.keys(data.basin_routing_times).map(Number).sort((a,b)=>a-b);
  durations.forEach(d => {
      const opt = document.createElement("option");
      opt.value = d;
      opt.textContent = d + " min";
        durSelect.appendChild(opt);
      });

  // Render chart for first duration
  renderResultsDashboard();
}

function renderResultsDashboard() {
    const durSelect = document.getElementById("dashboard-duration-select");
    const dur = parseInt(durSelect.value);

    if (!simulationData || !simulationData.basin_routing_times || !simulationData.basin_routing_times[dur]) return;

    const times = simulationData.basin_routing_times[dur];
    const depthsByPattern = simulationData.basin_routing_depths[dur];
    const moundByPattern = simulationData.basin_routing_mound ? simulationData.basin_routing_mound[dur] : null;
    const infilByPattern = simulationData.basin_routing_infil ? simulationData.basin_routing_infil[dur] : null;
    const cumInfilByPattern = simulationData.basin_routing_cum_infil ? simulationData.basin_routing_cum_infil[dur] : null;

    // Allowable Depth
    const allowableDepth = parseFloat(document.getElementById("inp-basin-depth").value) || 1.2;

    // Find median peak depth
    let peakDepths = [];
    let patternPeakMap = {};
    for (const [patternRank, depths] of Object.entries(depthsByPattern)) {
        const peak = Math.max(...depths);
        peakDepths.push(peak);
        patternPeakMap[patternRank] = peak;
    }
    peakDepths.sort((a,b) => a-b);
    let medianPeak = 0;
    if (peakDepths.length > 0) {
        medianPeak = peakDepths[Math.floor(peakDepths.length / 2)];
    }

    // Find pattern closest to median
    let medianPattern = null;
    let minDiff = Infinity;
    for (const [patternRank, peak] of Object.entries(patternPeakMap)) {
        const diff = Math.abs(peak - medianPeak);
        if (diff < minDiff) {
            minDiff = diff;
            medianPattern = patternRank;
        }
    }

    // Check if spilled
    const spilled = medianPeak > allowableDepth;
    const spillWarning = document.getElementById("spill-warning");
    if (spillWarning) {
        if (spilled) {
            spillWarning.style.display = "block";
            const spillVol = simulationData.model_runs && simulationData.model_runs.length > 0 ? (simulationData.model_runs[0].depth_summary.total_overflow_m3 || 0) : 0;
            spillWarning.innerHTML = `⚠️ Basin spills in the median storm. Approximate overflow volume: ${spillVol.toFixed(2)} m³.`;
        } else {
            spillWarning.style.display = "none";
        }
    }

    const datasets = [];
    for (const [patternRank, depths] of Object.entries(depthsByPattern)) {
        const isMedian = patternRank === medianPattern;
        datasets.push({
            label: `Pattern ${patternRank}`,
            data: times.map((t, i) => ({ x: t, y: depths[i] })),
            borderColor: isMedian ? "#1a6b4f" : "rgba(100,116,139,0.3)",
            borderWidth: isMedian ? 3 : 1,
            pointRadius: 0,
            fill: false,
            tension: 0.1,
            order: isMedian ? 1 : 2
        });
    }

    const ctx = document.getElementById("dashboard-chart").getContext("2d");
    if (dashboardChartInstance) dashboardChartInstance.destroy();
    dashboardChartInstance = new Chart(ctx, {
        type: 'line',
        data: { datasets: datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                title: { display: true, text: `Ponded Depth for ${dur} min Storm`, font: { size: 14 } },
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            return `Pattern ${context.dataset.label.replace('Pattern ', '')}: ${context.parsed.y.toFixed(3)} m`;
                        }
                    }
                },
                annotation: {
                    annotations: {
                        line1: {
                            type: 'line',
                            yMin: allowableDepth,
                            yMax: allowableDepth,
                            borderColor: 'red',
                            borderWidth: 2,
                            borderDash: [5, 5],
                            label: {
                                display: true,
                                content: 'Allowable Depth (' + allowableDepth.toFixed(2) + 'm)',
                                position: 'start'
                            }
                        }
                    }
                }
            },
            scales: {
                x: { type: 'linear', title: { display: true, text: "Time (minutes)" } },
                y: { title: { display: true, text: "Water Depth (m)" }, min: 0 }
            }
        }
    });

    // Render secondary chart for Median Pattern
    const secCtx = document.getElementById("dashboard-secondary-chart").getContext("2d");
    if (dashboardSecondaryChartInstance) dashboardSecondaryChartInstance.destroy();

    if (moundByPattern && infilByPattern && cumInfilByPattern && medianPattern) {
        const mound = moundByPattern[medianPattern];
        const infil = infilByPattern[medianPattern];
        const cumInfil = cumInfilByPattern[medianPattern];

        dashboardSecondaryChartInstance = new Chart(secCtx, {
            type: 'line',
            data: {
                datasets: [
                    {
                        label: 'Mound Height (m)',
                        data: times.map((t, i) => ({ x: t, y: mound[i] })),
                        borderColor: '#2563eb',
                        borderWidth: 2,
                        pointRadius: 0,
                        fill: false,
                        tension: 0.1,
                        yAxisID: 'y'
                    },
                    {
                        label: 'Effective Infil (m/day)',
                        data: times.map((t, i) => ({ x: t, y: infil[i] })),
                        borderColor: '#16a34a',
                        borderWidth: 2,
                        pointRadius: 0,
                        fill: false,
                        tension: 0.1,
                        yAxisID: 'y'
                    },
                    {
                        label: 'Cum. Infiltration (m³)',
                        data: times.map((t, i) => ({ x: t, y: cumInfil[i] })),
                        borderColor: '#9333ea',
                        borderWidth: 2,
                        pointRadius: 0,
                        fill: false,
                        tension: 0.1,
                        yAxisID: 'y1'
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    title: { display: true, text: `Groundwater Response (Median Pattern ${medianPattern})`, font: { size: 14 } },
                    legend: { display: true, position: 'bottom' }
                },
                scales: {
                    x: { type: 'linear', title: { display: true, text: "Time (minutes)" } },
                    y: {
                        type: 'linear',
                        display: true,
                        position: 'left',
                        title: { display: true, text: "Height (m) / Rate (m/d)" },
                        min: 0
                    },
                    y1: {
                        type: 'linear',
                        display: true,
                        position: 'right',
                        title: { display: true, text: "Cum. Vol (m³)" },
                        min: 0,
                        grid: { drawOnChartArea: false }
                    }
                }
            }
        });
    }
}

function showCriticalDuration() {
    if (!simulationData || !simulationData.model_runs || !simulationData.model_runs.length) return;
    const cd = simulationData.model_runs[0].depth_summary.critical_duration_minutes;
    const durSelect = document.getElementById("dashboard-duration-select");
    durSelect.value = cd;
    renderResultsDashboard();
}

function showCriticalDrawdown() {
    if (!simulationData || !simulationData.model_runs || !simulationData.model_runs.length) return;
    const cd = simulationData.model_runs[0].drawdown_summary.critical_duration_minutes;
    const durSelect = document.getElementById("dashboard-duration-select");
    durSelect.value = cd;
    renderResultsDashboard();
}

// Open the Maintenance Planning tab WITHOUT running. The user reviews/edits the
// clogging inputs (analysis years, final clogged K, final thickness) and then
// presses "Run Analysis" inside the tab to start. (Previously the dashboard
// button auto-ran the analysis with the default values, which was a bug.)
function openMaintenancePlanning() {
    const tabBtn = document.querySelector('.tab-btn[data-tab="tab-clogging"]');
    if (tabBtn) tabBtn.click();
}

async function runCloggingAnalysis() {
    if (!simulationData || !lastSimRequest) {
        alert("Please run a base simulation first.");
        return;
    }

    const cloggingYrs = parseInt(document.getElementById("inp-clog-years").value);
    const finalK = parseFloat(document.getElementById("inp-clog-k").value);
    const finalLRaw = document.getElementById("inp-clog-l").value;
    const finalL = finalLRaw ? parseFloat(finalLRaw) : null;

    if (isNaN(cloggingYrs) || isNaN(finalK) || (finalL !== null && isNaN(finalL))) {
        alert("Please enter valid clogging parameters.");
        return;
    }

    let cd = 60;
    let cr = 4;
    const selectedModel = simulationData.selected_model || "green_ampt_hantush";
    if (simulationData.model_runs) {
        const run = simulationData.model_runs.find(r => r.model_key === selectedModel) || simulationData.model_runs[0];
        if (run) {
            const sum = run.depth_summary || run.summary;
            if (sum) {
                cd = sum.critical_duration_minutes || sum.duration_minutes || 60;
                cr = sum.critical_pattern_rank || sum.pattern_rank || 4;
            }
        }
    }

    const payload = {
        // Reuse the EXACT design-run parameters so year 0 reproduces the
        // unclogged assessment (same U, groundwater levels, design AEP, K, etc.).
        latitude: lastSimRequest.latitude,
        longitude: lastSimRequest.longitude,
        catchments: lastSimRequest.catchments,
        design_aep_percent: lastSimRequest.design_aep_percent,
        critical_duration_minutes: cd,
        critical_pattern_rank: cr,
        basin_base_length_m: lastSimRequest.basin_base_length_m,
        basin_base_width_m: lastSimRequest.basin_base_width_m,
        basin_side_slope_ratio: lastSimRequest.basin_side_slope_ratio,
        basin_max_depth_m: lastSimRequest.basin_max_depth_m,
        initial_moisture_deficit: lastSimRequest.initial_moisture_deficit,
        capillary_suction_head_m: lastSimRequest.capillary_suction_head_m,
        specific_yield: lastSimRequest.specific_yield,
        vertical_k_mm_per_hr: lastSimRequest.vertical_k_mm_per_hr,
        horizontal_k_mm_per_hr: lastSimRequest.horizontal_k_mm_per_hr,
        soil_moderation_factor: lastSimRequest.soil_moderation_factor,
        surface_level_m_ahd: lastSimRequest.surface_level_m_ahd,
        design_gwl_m_ahd: lastSimRequest.design_gwl_m_ahd,
        base_aquifer_level_m_ahd: lastSimRequest.base_aquifer_level_m_ahd,
        basin_side_infil_enabled: lastSimRequest.basin_side_infil_enabled,
        clogging_years: cloggingYrs,
        final_k_cl_m_per_day: finalK,
        final_l_cl_m: finalL,
        use_live_data: lastSimRequest.use_live_data,
        climate_scenario: lastSimRequest.climate_scenario,
        climate_epoch: lastSimRequest.climate_epoch
    };

    // ── UI: show progress panel, reset state ──────────────────────────
    const loading = document.getElementById("clogging-loading");
    const loadingText = document.getElementById("clogging-loading-text");
    const progressBar = document.getElementById("clogging-progress-bar");
    const chartContainer = document.getElementById("clogging-chart-container");
    const tableContainer = document.getElementById("clogging-table-container");
    const dashboard = document.getElementById("clogging-dashboard");
    const tableBody = document.getElementById("clogging-table-body");

    loading.style.display = "";
    chartContainer.style.display = "none";
    tableContainer.style.display = "none";
    dashboard.style.display = "none";
    if (progressBar) progressBar.style.width = "0%";
    if (loadingText) loadingText.textContent = "Starting clogging analysis…";
    tableBody.innerHTML = "";
    cloggingTimelineData = null;
    cloggingSelectedYearRow = null;

    try {
        payload.project_code = document.getElementById("inp-project-code").value.trim() || null;
        const result = await submitAnalysis("/api/analyses/clogging", payload, (event) => {
          if (event.type !== "progress") return;
          if (event.phase === "setup") {
            if (loadingText) loadingText.textContent = event.message || "Preparing hydrology...";
            if (progressBar) progressBar.style.width = "5%";
          } else if (event.phase === "routing") {
            const pct = event.total > 0 ? (event.step / event.total) * 90 + 5 : 50;
            if (progressBar) progressBar.style.width = pct.toFixed(1) + "%";
            if (loadingText) loadingText.textContent = `Routing year ${event.year} of ${event.total - 1}...`;
          }
        });

        if (progressBar) progressBar.style.width = "100%";
        if (loadingText) loadingText.textContent = "Done.";
        cloggingTimelineData = result;
        tableBody.innerHTML = "";
        result.timeline.forEach(appendCloggingYearRow);
        renderCloggingSummaryChart(result);
        tableContainer.style.display = "";

        // Auto-select the final year so the dashboard isn't empty.
        if (cloggingTimelineData && cloggingTimelineData.timeline.length > 0) {
            renderCloggingYearDashboard(cloggingTimelineData.timeline.length - 1);
        }
    } catch (e) {
        alert("Clogging analysis failed: " + e.message);
    } finally {
        loading.style.display = "none";
        chartContainer.style.display = "";
    }
}


/** Append one year's result as a clickable row in the clogging table.
 *  Header columns: Year | Clogged K (m/day) | Clogged Thickness (m) |
 *  Peak Depth (m) | Drain Time (hours). Spill status is shown via a
 *  highlight + title tooltip (kept off the visible columns to match the
 *  existing 5-column table header). */
function appendCloggingYearRow(yearResult) {
    const tableBody = document.getElementById("clogging-table-body");
    const row = document.createElement("tr");
    row.style.cursor = "pointer";
    row.dataset.year = yearResult.year;
    if (yearResult.spilled) {
        row.style.background = "#fee2e2";
        row.title = "Basin overtops in this year (peak depth exceeds max depth).";
    }
    row.innerHTML =
        "<td>" + yearResult.year + "</td>" +
        "<td>" + Number(yearResult.k_cl_m_per_day).toFixed(4) + "</td>" +
        "<td>" + Number(yearResult.l_cl_m).toFixed(4) + "</td>" +
        "<td>" + Number(yearResult.peak_depth_m).toFixed(3) + "</td>" +
        "<td>" + Number(yearResult.drain_time_hours).toFixed(2) + "</td>";
    row.addEventListener("click", function () {
        renderCloggingYearDashboard(Number(row.dataset.year));
    });
    tableBody.appendChild(row);
}


/** Render the summary timeline chart (drain time + peak depth vs year). */
function renderCloggingSummaryChart(data) {
    const years = data.timeline.map(d => d.year);
    const drainTimes = data.timeline.map(d => d.drain_time_hours);
    const depths = data.timeline.map(d => d.peak_depth_m);
    const kcl = data.timeline.map(d => d.k_cl_m_per_day);
    const lcl = data.timeline.map(d => d.l_cl_m);

    const ctx = document.getElementById("clogging-chart").getContext("2d");
    if (dashboardCloggingChartInstance) dashboardCloggingChartInstance.destroy();

    dashboardCloggingChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: years,
            datasets: [
                {
                    label: 'Drawdown Time (hrs)',
                    data: drainTimes,
                    borderColor: '#d97706',
                    backgroundColor: 'rgba(217, 119, 6, 0.2)',
                    borderWidth: 3,
                    fill: true,
                    tension: 0.2,
                    yAxisID: 'y'
                },
                {
                    label: 'Peak Depth (m)',
                    data: depths,
                    borderColor: '#2563eb',
                    borderWidth: 2,
                    borderDash: [5, 5],
                    fill: false,
                    tension: 0.2,
                    yAxisID: 'y1'
                },
                {
                    label: 'Clogged K (m/day)',
                    data: kcl,
                    borderColor: '#16a34a',
                    borderWidth: 2,
                    pointStyle: 'rectRot',
                    fill: false,
                    tension: 0.2,
                    yAxisID: 'y2'
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                title: { display: true, text: "Projected Clogging Impact over Time", font: { size: 14 } },
                legend: { display: true, position: 'bottom' },
                tooltip: {
                    callbacks: {
                        afterBody: function (items) {
                            const i = items[0].dataIndex;
                            return [
                                "Clogged K: " + Number(kcl[i]).toFixed(3) + " m/day",
                                "Clogged thickness: " + Number(lcl[i]).toFixed(3) + " m",
                            ];
                        }
                    }
                }
            },
            scales: {
                x: { title: { display: true, text: "Years since commissioning" } },
                y: {
                    type: 'linear',
                    display: true,
                    position: 'left',
                    title: { display: true, text: "Drawdown Time (hours)" }, min: 0
                },
                y1: {
                    type: 'linear',
                    display: true,
                    position: 'right',
                    title: { display: true, text: "Peak Depth (m)" }, min: 0,
                    grid: { drawOnChartArea: false }
                },
                y2: {
                    type: 'linear',
                    display: false,   // hidden axis — Clogged K scaling only (shown via tooltip + legend)
                    position: 'right',
                    min: 0
                }
            }
        }
    });
}


/** Render the ponded-depth + drawdown timeseries for the selected clogging
 *  year into the dashboard canvases.
 *
 *  - clog-chart-stage   : ponded depth (m) vs time, depth-critical event
 *  - clog-chart-mound   : drawdown (recession) depth (m) vs time, drawdown-critical event
 *  - clog-chart-infil / clog-chart-cuminfil : hidden (not used for this view)
 */
function renderCloggingYearDashboard(yearIdx) {
    if (!cloggingTimelineData || !cloggingTimelineData.timeline) return;
    const yr = cloggingTimelineData.timeline[yearIdx];
    if (!yr) return;

    cloggingSelectedYearRow = yearIdx;

    // Highlight the selected row; clear the others.
    document.querySelectorAll("#clogging-table-body tr").forEach(function (tr) {
        tr.style.outline = (Number(tr.dataset.year) === yr.year) ? "2px solid #2563eb" : "";
        if (Number(tr.dataset.year) !== yr.year && tr.style.background === "rgb(37, 99, 235)") {
            tr.style.background = "";
        }
    });

    const dashboard = document.getElementById("clogging-dashboard");
    const title = document.getElementById("clogging-dash-title");
    if (title) {
        title.textContent = "Year " + yr.year + " — Clogged K = " +
            Number(yr.k_cl_m_per_day).toFixed(3) + " m/day, Thickness = " +
            Number(yr.l_cl_m).toFixed(3) + " m" + (yr.spilled ? "  (⚠ overtops)" : "");
    }
    dashboard.style.display = "";

    const tsDepth = yr.timeseries;            // depth-critical event timeseries
    const tsDrawdown = yr.timeseries_drawdown; // drawdown-critical event timeseries
    if (!tsDepth || !tsDrawdown) return;

    // Convert minutes → hours for readable x-axis labels.
    const toHours = function (mins) {
        return mins.map(function (m) { return (m / 60.0).toFixed(2); });
    };

    // ── Ponded depth chart (depth-critical event) ──────────────────────
    const stageCanvas = document.getElementById("clog-chart-stage");
    if (clogYearDepthChartInstance) clogYearDepthChartInstance.destroy();
    clogYearDepthChartInstance = new Chart(stageCanvas.getContext("2d"), {
        type: 'line',
        data: {
            labels: toHours(tsDepth.time_minutes),
            datasets: [{
                label: 'Ponded depth (m)',
                data: tsDepth.depth_m,
                borderColor: '#2563eb',
                backgroundColor: 'rgba(37, 99, 235, 0.18)',
                borderWidth: 2,
                fill: true,
                tension: 0.2,
                pointRadius: 0
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                title: { display: true, text: "Ponded Depth — Year " + yr.year + " (depth-critical)", font: { size: 13 } },
                legend: { display: false }
            },
            scales: {
                x: { title: { display: true, text: "Time (hours)" } },
                y: { title: { display: true, text: "Depth (m)" }, min: 0 }
            }
        }
    });

    // ── Drawdown chart (drawdown-critical event recession) ─────────────
    const ddCanvas = document.getElementById("clog-chart-mound");
    if (clogYearDrawdownChartInstance) clogYearDrawdownChartInstance.destroy();
    clogYearDrawdownChartInstance = new Chart(ddCanvas.getContext("2d"), {
        type: 'line',
        data: {
            labels: toHours(tsDrawdown.time_minutes),
            datasets: [{
                label: 'Ponded depth — drawdown (m)',
                data: tsDrawdown.depth_m,
                borderColor: '#d97706',
                backgroundColor: 'rgba(217, 119, 6, 0.18)',
                borderWidth: 2,
                fill: true,
                tension: 0.2,
                pointRadius: 0
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                title: { display: true, text: "Drawdown — Year " + yr.year + " (drawdown-critical)", font: { size: 13 } },
                legend: { display: false }
            },
            scales: {
                x: { title: { display: true, text: "Time (hours)" } },
                y: { title: { display: true, text: "Depth (m)" }, min: 0 }
            }
        }
    });

    // Hide the two unused canvases for this view.
    const infilCard = document.getElementById("clog-chart-infil");
    const cumInfilCard = document.getElementById("clog-chart-cuminfil");
    if (infilCard && infilCard.parentElement) infilCard.parentElement.style.display = "none";
    if (cumInfilCard && cumInfilCard.parentElement) cumInfilCard.parentElement.style.display = "none";
}


// ── PDF Report ──────────────────────────────────────────────────────────
// Renders a Chart.js config onto a detached canvas and returns a PNG data URL.
function _renderChartToImage(config, width = 920, height = 440) {
    const holder = document.createElement("div");
    holder.style.cssText =
        `position:absolute;left:-10000px;top:0;width:${width}px;height:${height}px;`;
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    holder.appendChild(canvas);
    document.body.appendChild(holder);
    config.options = config.options || {};
    config.options.responsive = false;
    config.options.maintainAspectRatio = false;
    config.options.animation = false;
    config.options.devicePixelRatio = 2;
    let url = null;
    try {
        const chart = new Chart(canvas.getContext("2d"), config);
        url = chart.toBase64Image("image/png", 1.0);
        chart.destroy();
    } catch (e) {
        console.warn("chart image failed:", e);
    }
    document.body.removeChild(holder);
    return url ? { url, w: width, h: height } : null;
}

// Ponded-depth-vs-time chart (all patterns, median highlighted) for one duration.
function _pondedDepthImage(data, dur, title) {
    if (!data.basin_routing_times || !data.basin_routing_times[dur]) return null;
    const times = data.basin_routing_times[dur];
    const depthsByPattern = data.basin_routing_depths[dur];
    if (!depthsByPattern) return null;
    const allowable = parseFloat(document.getElementById("inp-basin-depth").value) || 1.2;

    let peaks = [], peakMap = {};
    for (const [rank, depths] of Object.entries(depthsByPattern)) {
        const p = Math.max(...depths); peaks.push(p); peakMap[rank] = p;
    }
    peaks.sort((a, b) => a - b);
    const medianPeak = peaks.length ? peaks[Math.floor(peaks.length / 2)] : 0;
    let medianPattern = null, minDiff = Infinity;
    for (const [rank, p] of Object.entries(peakMap)) {
        const d = Math.abs(p - medianPeak);
        if (d < minDiff) { minDiff = d; medianPattern = rank; }
    }
    const datasets = [];
    for (const [rank, depths] of Object.entries(depthsByPattern)) {
        const isMed = rank === medianPattern;
        datasets.push({
            label: `Pattern ${rank}`,
            data: times.map((t, i) => ({ x: t, y: depths[i] })),
            borderColor: isMed ? "#1a6b4f" : "rgba(100,116,139,0.35)",
            borderWidth: isMed ? 3 : 1,
            pointRadius: 0, fill: false, tension: 0.1,
        });
    }
    return _renderChartToImage({
        type: "line",
        data: { datasets },
        options: {
            plugins: {
                title: { display: true, text: title, font: { size: 15 } },
                legend: { display: false },
                annotation: {
                    annotations: {
                        allow: {
                            type: "line", yMin: allowable, yMax: allowable,
                            borderColor: "red", borderWidth: 2, borderDash: [5, 5],
                            label: { display: true, content: `Allowable ${allowable.toFixed(2)} m`, position: "start" },
                        },
                    },
                },
            },
            scales: {
                x: { type: "linear", title: { display: true, text: "Time (minutes)" } },
                y: { title: { display: true, text: "Water Depth (m)" }, min: 0 },
            },
        },
    });
}

// Clogging timeline chart (drawdown time + peak depth vs year).
function _cloggingTimelineImage(timeline) {
    const years = timeline.map(d => d.year);
    return _renderChartToImage({
        type: "line",
        data: {
            labels: years,
            datasets: [
                {
                    label: "Drawdown Time (hrs)", data: timeline.map(d => d.drain_time_hours),
                    borderColor: "#d97706", backgroundColor: "rgba(217,119,6,0.2)",
                    borderWidth: 3, fill: true, tension: 0.2, yAxisID: "y", pointRadius: 0,
                },
                {
                    label: "Peak Depth (m)", data: timeline.map(d => d.peak_depth_m),
                    borderColor: "#2563eb", borderWidth: 2, borderDash: [5, 5],
                    fill: false, tension: 0.2, yAxisID: "y1", pointRadius: 0,
                },
            ],
        },
        options: {
            plugins: {
                title: { display: true, text: "Projected Clogging Impact over Time", font: { size: 15 } },
                legend: { display: true, position: "bottom" },
            },
            scales: {
                x: { title: { display: true, text: "Years since commissioning" } },
                y: { position: "left", title: { display: true, text: "Drawdown Time (hours)" }, min: 0 },
                y1: { position: "right", title: { display: true, text: "Peak Depth (m)" }, min: 0, grid: { drawOnChartArea: false } },
            },
        },
    });
}

function _canvasImage(id) {
    const c = document.getElementById(id);
    if (!c || !c.width || !c.height) return null;
    try {
        return { url: c.toDataURL("image/png"), w: c.width, h: c.height };
    } catch (e) {
        return null;
    }
}

// Export the full design-storm runoff hydrographs as a CSV download.
// Long format: Hydrograph, Time_min, Discharge_cms (handles varying
// timesteps/lengths across storms cleanly).
function exportHydrographsCsv() {
    const hydros = (simulationData && simulationData.hydrographs) || [];
    if (!hydros.length) return;
    const rows = [["Hydrograph", "Time_min", "Discharge_cms"]];
    hydros.forEach((h) => {
        const dt = h.timestep_minutes || 1;
        (h.discharge_cms || []).forEach((q, i) => {
            rows.push([h.key, (i * dt).toFixed(2), Number(q).toFixed(6)]);
        });
    });
    const csv = rows
        .map((r) => r.map((c) => {
            const s = String(c);
            return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
        }).join(","))
        .join("\r\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `GAH3D_Hydrographs_${(simulationData.project_name || "basin").replace(/[^a-z0-9]/gi, "_")}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

function generateReport() {
    if (!simulationData) {
        alert("Please run a simulation first.");
        return;
    }
    // Gate: a Maintenance Planning (clogging) assessment MUST be completed first.
    if (!cloggingTimelineData || !cloggingTimelineData.timeline || cloggingTimelineData.timeline.length === 0) {
        alert(
            "Clogging assessment required before generating a report.\n\n" +
            "The basin must be designed for its end-of-life (clogged) performance. " +
            "Open the Results Dashboard and press \u201cRun Maintenance Analysis\u201d " +
            "(or use the Maintenance Planning tab) to complete the clogging timeline, " +
            "then generate the report.\n\n" +
            "The report cannot be produced until clogging has been considered."
        );
        return;
    }
    if (typeof window.jspdf === "undefined" || !window.jspdf.jsPDF) {
        alert("PDF library failed to load. Check your internet connection and try again.");
        return;
    }

    const { jsPDF } = window.jspdf;
    const doc = new jsPDF({ unit: "pt", format: "a4" });
    const pageW = doc.internal.pageSize.getWidth();
    const pageH = doc.internal.pageSize.getHeight();
    const margin = 40;
    const contentW = pageW - 2 * margin;
    let y = margin;

    const GREEN = [26, 107, 79];
    const INK = [30, 41, 59];

    function ensure(space) {
        if (y + space > pageH - margin) { doc.addPage(); y = margin; }
    }
    function heading(text, size = 14, gap = 8) {
        ensure(size + 14);
        doc.setFont("helvetica", "bold"); doc.setFontSize(size);
        doc.setTextColor(...GREEN); doc.text(text, margin, y);
        y += size + gap; doc.setTextColor(...INK);
    }
    function kv(label, value) {
        ensure(14);
        doc.setFont("helvetica", "bold"); doc.setFontSize(9); doc.setTextColor(...INK);
        doc.text(String(label), margin, y);
        doc.setFont("helvetica", "normal");
        const lines = doc.splitTextToSize(String(value), contentW - 165);
        doc.text(lines, margin + 165, y);
        y += Math.max(13, lines.length * 12);
    }
    function para(text) {
        doc.setFont("helvetica", "normal"); doc.setFontSize(9); doc.setTextColor(...INK);
        const lines = doc.splitTextToSize(String(text), contentW);
        ensure(lines.length * 12 + 4);
        doc.text(lines, margin, y);
        y += lines.length * 12 + 4;
    }
    function image(img, caption, maxW) {
        if (!img) return;
        const drawW = Math.min(maxW || contentW, contentW);
        const drawH = drawW * (img.h / img.w);
        ensure(drawH + (caption ? 16 : 6));
        doc.addImage(img.url, "PNG", margin, y, drawW, drawH);
        y += drawH + 4;
        if (caption) {
            doc.setFont("helvetica", "italic"); doc.setFontSize(8); doc.setTextColor(100, 116, 139);
            doc.text(caption, margin, y); y += 12; doc.setTextColor(...INK);
        }
    }
    function table(head, body) {
        doc.autoTable({
            head: [head], body: body, startY: y, margin: { left: margin, right: margin },
            styles: { fontSize: 8, cellPadding: 3 },
            headStyles: { fillColor: GREEN, textColor: 255 },
            theme: "grid",
        });
        y = doc.lastAutoTable.finalY + 12;
    }

    // ── Gather inputs ──
    const lat = document.getElementById("inp-lat").value;
    const lng = document.getElementById("inp-lng").value;
    const aeps = Array.from(document.getElementById("inp-aeps").selectedOptions).map(o => o.text).join(", ");
    const durations = getSelectedDurations().join(", ");
    const kv_v = document.getElementById("inp-kv").value;
    const kh_v = document.getElementById("inp-kh").value;
    const u_v = document.getElementById("inp-safety").value;
    const bl = document.getElementById("inp-basin-length").value;
    const bw = document.getElementById("inp-basin-width").value;
    const bs = document.getElementById("inp-basin-side-slope").value;
    const bd = document.getElementById("inp-basin-depth").value;
    const deficit = document.getElementById("inp-basin-deficit").value;
    const suction = document.getElementById("inp-basin-suction").value;
    const sy = document.getElementById("inp-basin-specific-yield").value;
    const soilProfile = document.getElementById("inp-basin-soil-profile").value;
    const paramMode = document.getElementById("inp-basin-param-mode").value;
    const invertLvl = document.getElementById("inp-surface-lvl").value;
    const gwl = document.getElementById("inp-design-gwl").value;
    const baseAq = document.getElementById("inp-base-aquifer-lvl").value;
    const depthToGw = (parseFloat(invertLvl) - parseFloat(gwl));
    const ccLabel = simulationData.climate_scenario_label || "Historical";

    // ── Title ──
    doc.setFont("helvetica", "bold"); doc.setFontSize(20); doc.setTextColor(...GREEN);
    doc.text("GAH-3D Basin Design Report", margin, y); y += 24;
    doc.setFontSize(12); doc.setTextColor(...INK);
    doc.text(simulationData.project_name || "Infiltration Basin", margin, y); y += 16;
    doc.setFont("helvetica", "normal"); doc.setFontSize(9); doc.setTextColor(100, 116, 139);
    doc.text(`Generated ${new Date().toLocaleString()}  |  Climate scenario: ${ccLabel}`, margin, y);
    y += 18; doc.setTextColor(...INK);

    // ── 1. Location ──
    heading("1. Site Location");
    kv("Latitude", lat);
    kv("Longitude", lng);

    // ── 2. Hydrology ──
    heading("2. Hydrology");
    kv("AEP(s) analysed", aeps);
    kv("Storm durations (min)", durations || "Default set");
    kv("Climate scenario", ccLabel);
    if (catchments && catchments.length) {
        table(
            ["Catchment", "Area (ha)", "Paved %", "Supp. %", "Grassed %"],
            catchments.map((c, i) => [
                c.name || `Catchment ${i + 1}`,
                Number(c.area_ha).toFixed(3),
                (c.paved_fraction * 100).toFixed(0),
                (c.supplementary_fraction * 100).toFixed(0),
                (c.grassed_fraction * 100).toFixed(0),
            ])
        );
    }
    para("Full design-storm runoff hydrographs are exported separately as a CSV file " +
        "(downloaded alongside this report).");

    // ── 3. Soil parameters ──
    heading("3. Soil Parameters");
    kv("Vertical conductivity (Kv)", `${kv_v} m/day`);
    kv("Horizontal conductivity (Kh)", kh_v ? `${kh_v} m/day` : `Default anisotropic (Kh = 5xKv = ${(kv_v * 5).toFixed(1)} m/day)`);
    kv("Soil moderation factor (U)", u_v);
    kv("Soil-type default", soilProfile);
    kv("Parameter mode", paramMode === "custom" ? "Custom values" : "Soil-type defaults");
    kv("Initial moisture deficit (delta-theta)", deficit);
    kv("Capillary suction head (psi)", `${suction} m`);
    kv("Routing model", simulationData.selected_model || "Green-Ampt/Hantush");

    // ── 4. Groundwater ──
    heading("4. Groundwater");
    kv("Specific yield (Sy)", sy);
    kv("Basin invert level", `${invertLvl} m AHD`);
    kv("Design groundwater level", `${gwl} m AHD`);
    kv("Base aquifer level", `${baseAq} m AHD`);
    kv("Depth to groundwater", `${isNaN(depthToGw) ? "-" : depthToGw.toFixed(2)} m below invert`);

    // ── 5. Geometry: cross-section + plan ──
    heading("5. Basin Geometry - Section & Plan");
    kv("Base length x width", `${bl} m x ${bw} m`);
    kv("Side slope", `1 : ${bs}`);
    kv("Maximum depth", `${bd} m`);
    y += 4;
    image(_canvasImage("section-canvas"), "Cross-section (long axis). Water level & mound shown at critical event.", contentW);
    image(_canvasImage("plan-canvas"), "Plan (top-down): base footprint, top-of-batter outline & structures.", contentW * 0.7);

    // ── 6. Results ──
    doc.addPage(); y = margin;
    heading("6. Results Summary");
    if (simulationData.model_runs && simulationData.model_runs.length) {
        const run = simulationData.model_runs[0];
        const rows = [];
        const mkRow = (label, s) => [
            label, `${s.critical_duration_minutes} (Rank ${s.critical_pattern_rank})`,
            (s.max_storage_m3 || 0).toFixed(2), (s.peak_depth_m || 0).toFixed(3),
            (s.peak_mound_height_m || 0).toFixed(3), s.spilled ? "Yes" : "No",
            (s.total_overflow_m3 || 0).toFixed(2),
        ];
        if (run.depth_summary) rows.push(mkRow("Critical Peak Depth", run.depth_summary));
        if (run.drawdown_summary) rows.push(mkRow("Critical Drawdown", run.drawdown_summary));
        table(
            ["Critical Event", "Dur (min)", "Peak Vol (m³)", "Peak Depth (m)", "Peak Mound (m)", "Exceeds?", "Spill (m³)"],
            rows
        );
    }
    // Median depth per duration
    const medImg = medianDepthChartInstance
        ? { url: medianDepthChartInstance.toBase64Image("image/png", 1.0), w: 920, h: 300 }
        : null;
    image(medImg, "Median peak ponded depth for each storm duration (allowable depth dashed).", contentW);

    // Critical ponded depth + drawdown graphs
    const run0 = simulationData.model_runs && simulationData.model_runs[0];
    if (run0) {
        const depthDur = run0.depth_summary.critical_duration_minutes;
        const ddDur = run0.drawdown_summary.critical_duration_minutes;
        heading("Critical Ponded Depth", 12, 6);
        image(_pondedDepthImage(simulationData, depthDur, `Ponded Depth \u2014 Critical Depth Event (${depthDur} min)`),
            null, contentW);
        heading("Critical Drawdown", 12, 6);
        image(_pondedDepthImage(simulationData, ddDur, `Ponded Depth \u2014 Critical Drawdown Event (${ddDur} min)`),
            null, contentW);
    }

    // ── 7. Clogging assessment ──
    doc.addPage(); y = margin;
    heading("7. Clogging Assessment (Maintenance Planning)");
    para("End-of-life performance with the agreed clogged layer applied over the analysis timeline. " +
        "Clogging parameters (K, thickness) and horizon should be agreed with the asset owner.");
    image(_cloggingTimelineImage(cloggingTimelineData.timeline),
        "Projected peak depth and drawdown time as the basin clogs.", contentW);
    table(
        ["Year", "Clogged K (m/day)", "Clogged Thick. (m)", "Peak Depth (m)", "Drawdown (hrs)", "Overtops?"],
        cloggingTimelineData.timeline.map(d => [
            d.year, Number(d.k_cl_m_per_day).toFixed(4), Number(d.l_cl_m).toFixed(4),
            Number(d.peak_depth_m).toFixed(3), Number(d.drain_time_hours).toFixed(2),
            d.spilled ? "Yes" : "No",
        ])
    );

    // Footer page numbers
    const pageCount = doc.internal.getNumberOfPages();
    for (let i = 1; i <= pageCount; i++) {
        doc.setPage(i);
        doc.setFont("helvetica", "normal"); doc.setFontSize(8); doc.setTextColor(150, 160, 175);
        doc.text(`BaSIM GAH-3D  -  Page ${i} of ${pageCount}`, margin, pageH - 20);
    }

    const fname = `GAH3D_Report_${(simulationData.project_name || "basin").replace(/[^a-z0-9]/gi, "_")}.pdf`;
    exportHydrographsCsv();
    doc.save(fname);
}


function renderTimeSeriesCharts(containerId, items, yLabel, valuesFn, dtFn, chartType) {
  const container = document.getElementById(containerId);
  container.innerHTML = "";
  if (!items.length) {
    container.innerHTML = `<p style="color:var(--muted);padding:1rem">No data.</p>`;
    return;
  }

  // Group by duration extracted from key
  const groups = {};
  items.forEach((item) => {
    // key looks like "5% 60min Rank 1"
    const durMatch = item.key.match(/(\d+)min/);
    const groupKey = durMatch ? `${durMatch[1]} min duration` : "All";
    if (!groups[groupKey]) groups[groupKey] = [];
    groups[groupKey].push(item);
  });

  for (const [groupLabel, series] of Object.entries(groups)) {
    const wrap = document.createElement("div");
    wrap.className = "chart-wrap";
    wrap.innerHTML = `<h4 style="font-size:.82rem;color:var(--muted);margin-bottom:.4rem">${groupLabel}</h4><canvas></canvas>`;
    container.appendChild(wrap);
    const canvas = wrap.querySelector("canvas");

    const datasets = series.map((s, i) => {
      const values = valuesFn(s);
      const dt = dtFn(s);
      return {
        label: s.key,
        data: values.map((v, j) => ({ x: j * dt, y: v })),
        borderColor: COLORS[i % COLORS.length],
        backgroundColor: COLORS[i % COLORS.length] + "44",
        borderWidth: chartType === "line" ? 2 : 1,
        pointRadius: 0,
        fill: chartType === "bar",
        tension: 0.3,
      };
    });

    const chart = new Chart(canvas, {
      type: chartType === "bar" ? "bar" : "line",
      data: { datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { position: "bottom", labels: { font: { size: 11 } } },
        },
        scales: {
          x: {
            type: "linear",
            title: { display: true, text: "Time (min)" },
          },
          y: {
            title: { display: true, text: yLabel },
            beginAtZero: true,
          },
        },
      },
    });
    chartInstances.push(chart);
  }
}

// ── Cumulative volume charts ────────────────────────────────────────────
function renderCumulativeVolumeCharts(hydrographs) {
  const container = document.getElementById("hydro-charts");
  container.innerHTML = "";
  if (!hydrographs || !hydrographs.length) {
    container.innerHTML = `<p style="color:var(--muted);padding:1rem">No data.</p>`;
    return;
  }

  // Parse key → { aep, dur, rank }
  function parseKey(k) {
    const m = k.match(/^(.+?)\s+(\d+)min\s+Rank\s+(\d+)$/);
    return m ? { aep: m[1], dur: parseInt(m[2]), rank: parseInt(m[3]) } : null;
  }

  // Build cumulative volume series for each hydrograph
  function cumVol(h) {
    const dt_s = h.timestep_minutes * 60;
    let acc = 0;
    return h.discharge_cms.map((q) => { acc += q * dt_s; return acc; });
  }

  // Group by AEP+Duration
  const groups = {};
  hydrographs.forEach((h) => {
    const p = parseKey(h.key);
    if (!p) return;
    const gk = `${p.aep} ${p.dur}min`;
    if (!groups[gk]) groups[gk] = { aep: p.aep, dur: p.dur, items: [] };
    groups[gk].items.push({ ...h, rank: p.rank });
  });

  // Sort items by rank and find the median (4th-highest volume = rank sorted by volume, index 3)
  const medianSeries = []; // for summary chart

  for (const [gk, grp] of Object.entries(groups)) {
    // Sort by total volume descending → 4th item is median
    grp.items.sort((a, b) => {
      const va = a.discharge_cms.reduce((s, v) => s + v, 0);
      const vb = b.discharge_cms.reduce((s, v) => s + v, 0);
      return vb - va;
    });
    const medianIdx = Math.min(3, grp.items.length - 1); // 0-based: 4th highest

    const wrap = document.createElement("div");
    wrap.className = "chart-wrap";
    wrap.innerHTML = `<h4 style="font-size:.82rem;color:var(--muted);margin-bottom:.4rem">${gk}</h4><canvas></canvas>`;
    container.appendChild(wrap);
    const canvas = wrap.querySelector("canvas");

    const datasets = grp.items.map((h, i) => {
      const cv = cumVol(h);
      const isMedian = i === medianIdx;
      return {
        label: h.key + (isMedian ? " (median)" : ""),
        data: cv.map((v, j) => ({ x: j * h.timestep_minutes, y: v })),
        borderColor: isMedian ? COLORS[0] : "#ccc",
        backgroundColor: isMedian ? COLORS[0] + "22" : "transparent",
        borderWidth: isMedian ? 3 : 1,
        pointRadius: 0,
        fill: false,
        tension: 0.3,
        order: isMedian ? 0 : 1,
      };
    });

    const chart = new Chart(canvas, {
      type: "line",
      data: { datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { position: "bottom", labels: { font: { size: 11 },
            filter: (item) => item.text.includes("(median)") } },
        },
        scales: {
          x: { type: "linear", title: { display: true, text: "Time (min)" } },
          y: { title: { display: true, text: "Cumulative Volume (m³)" }, beginAtZero: true },
        },
      },
    });
    chartInstances.push(chart);

    // Collect median for summary
    const medH = grp.items[medianIdx];
    medianSeries.push({ key: gk + " (median)", dur: grp.dur, data: cumVol(medH), dt: medH.timestep_minutes });
  }

  // ── Summary chart: all median runs on one graph ──
  if (medianSeries.length > 1) {
    const wrap = document.createElement("div");
    wrap.className = "chart-wrap";
    wrap.innerHTML = `<h4 style="font-size:.85rem;color:var(--primary);margin-bottom:.4rem;font-weight:700">Summary — Median Cumulative Volumes</h4><canvas></canvas>`;
    container.insertBefore(wrap, container.firstChild);
    const canvas = wrap.querySelector("canvas");

    const datasets = medianSeries.map((s, i) => ({
      label: s.key,
      data: s.data.map((v, j) => ({ x: j * s.dt, y: v })),
      borderColor: COLORS[i % COLORS.length],
      borderWidth: 2.5,
      pointRadius: 0,
      fill: false,
      tension: 0.3,
    }));

    const chart = new Chart(canvas, {
      type: "line",
      data: { datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { position: "bottom", labels: { font: { size: 11 } } } },
        scales: {
          x: { type: "linear", title: { display: true, text: "Time (min)" } },
          y: { title: { display: true, text: "Cumulative Volume (m³)" }, beginAtZero: true },
        },
      },
    });
    chartInstances.push(chart);
  }
}



// ── Soakwell Performance chart ──────────────────────────────────────────
function renderSoakwellPerformanceChart(ts, design, structureType = "soakwell", modelLabel = "", modelSummary = null) {
  const container = document.getElementById("soakperf-charts");
  const structureLabel = getStructureLabel(structureType);
  container.innerHTML = "";
  if (!ts || !ts.time_minutes || !ts.time_minutes.length) {
    container.innerHTML = `<p style="color:var(--muted);padding:1rem">No ${structureLabel.toLowerCase()} time-series data available. Run a simulation first.</p>`;
    return;
  }

  // Build chart title with critical storm details
  let chartTitle = `${structureLabel} Performance`;
  if (modelSummary && Number.isFinite(Number(modelSummary.critical_duration_minutes))) {
    chartTitle += ` \u2014 Critical Storm: ${Number(modelSummary.critical_duration_minutes)} min duration, Temporal Pattern #${Number(modelSummary.critical_pattern_rank || 0)}`;
  } else if (design) {
    chartTitle += ` \u2014 Critical Storm: ${design.critical_duration_minutes} min duration, Temporal Pattern #${design.selected_pattern_rank}`;
  }
  if (modelLabel) {
    chartTitle += ` \u2014 ${modelLabel}`;
  }

  // Detect if spill occurred
  const hasSpill = ts.spill_flag && ts.spill_flag.some(f => f);
  const firstSpillIdx = hasSpill ? ts.spill_flag.indexOf(true) : -1;
  const lastSpillIdx = hasSpill ? ts.spill_flag.lastIndexOf(true) : -1;

  // Show spill warning banner
  if (hasSpill) {
    const banner = document.createElement("div");
    banner.style.cssText = "background:#fef2f2;border:1px solid #fca5a5;border-radius:6px;padding:.5rem .8rem;margin-bottom:.5rem;font-size:.82rem;color:#991b1b;font-weight:600";
    const spillStart = ts.time_minutes[firstSpillIdx];
    const spillEnd = ts.time_minutes[lastSpillIdx];
    const maxOverflow = ts.cumulative_overflow_m3 ? Math.max(...ts.cumulative_overflow_m3) : 0;
    banner.innerHTML = `⚠ ${structureLabel.toUpperCase()} SPILL detected from t = ${spillStart} min to t = ${spillEnd} min — max surface ponding volume: ${maxOverflow.toFixed(3)} m³`;
    container.appendChild(banner);
  }

  const wrap = document.createElement("div");
  wrap.className = "chart-wrap";
  wrap.style.height = "450px";
  wrap.innerHTML = `<h4 style="font-size:.85rem;color:var(--primary);margin-bottom:.4rem;font-weight:700">${chartTitle}</h4><canvas></canvas>`;
  container.appendChild(wrap);
  const canvas = wrap.querySelector("canvas");

  // For log scale, replace t=0 with a small positive value
  const timeData = ts.time_minutes.map(t => t === 0 ? 0.1 : t);

  // Build datasets
  const datasets = [
    {
      label: "Cumulative Inflow (m³)",
      data: timeData.map((t, i) => ({ x: t, y: ts.cumulative_inflow_m3[i] })),
      borderColor: "#3b82f6",
      backgroundColor: "#3b82f622",
      borderWidth: 2.5,
      pointRadius: 0,
      fill: false,
      tension: 0.3,
      yAxisID: "y",
    },
    {
      label: "Storage Volume (m³)",
      data: timeData.map((t, i) => ({ x: t, y: ts.storage_volume_m3[i] })),
      borderColor: "#f59e0b",
      backgroundColor: "#f59e0b22",
      borderWidth: 2.5,
      pointRadius: 0,
      fill: true,
      tension: 0.3,
      yAxisID: "y",
    },
    {
      label: "Cumulative Infiltration (m³)",
      data: timeData.map((t, i) => ({ x: t, y: ts.cumulative_infiltration_m3[i] })),
      borderColor: "#1a6b4f",
      backgroundColor: "#1a6b4f22",
      borderWidth: 2.5,
      pointRadius: 0,
      fill: false,
      tension: 0.3,
      yAxisID: "y",
    },
    {
      label: "Depth (m)",
      data: timeData.map((t, i) => ({ x: t, y: ts.depth_m[i] })),
      borderColor: "#ef4444",
      borderWidth: 2,
      borderDash: [6, 3],
      pointRadius: 0,
      fill: false,
      tension: 0.3,
      yAxisID: "y2",
    },
  ];

  // Add overflow / ponding series if there was a spill
  if (hasSpill && ts.cumulative_overflow_m3) {
    datasets.push({
      label: "Surface Ponding (m³)",
      data: timeData.map((t, i) => ({ x: t, y: ts.cumulative_overflow_m3[i] })),
      borderColor: "#dc2626",
      backgroundColor: "#dc262622",
      borderWidth: 2,
      pointRadius: 0,
      fill: true,
      tension: 0.3,
      yAxisID: "y",
    });
  }

  // Annotation plugin config for spill region + soakwell capacity line
  const annotations = {};
  // Soakwell capacity annotation (if we can compute it from max storage)
  // We infer capacity as the max storage volume while not spilling, or use the storage at first spill
  let soakwellCapacity = Math.max(...ts.storage_volume_m3);
  if (hasSpill && firstSpillIdx > 0) {
    // capacity is storage just before spill began
    soakwellCapacity = ts.storage_volume_m3[firstSpillIdx > 0 ? firstSpillIdx - 1 : 0];
  }

  const chart = new Chart(canvas, {
    type: "line",
    data: { datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { position: "bottom", labels: { font: { size: 11 } } },
        tooltip: {
          callbacks: {
            title: (items) => {
              if (!items.length) return "";
              const m = items[0].parsed.x;
              if (m < 1) return "0 min";
              if (m < 60) return Math.round(m) + " min";
              if (m < 1440) { const h = m / 60; return (h % 1 === 0 ? h : h.toFixed(1)) + " hr"; }
              const d = m / 1440; return (d % 1 === 0 ? d : d.toFixed(1)) + " days";
            },
            label: (ctx) => {
              const ds = ctx.dataset;
              const val = ctx.parsed.y.toFixed(3);
              // Add spill indicator in tooltip
              if (ts.spill_flag && ts.spill_flag[ctx.dataIndex]) {
                return `${ds.label}: ${val}  ⚠ SPILL`;
              }
              return `${ds.label}: ${val}`;
            },
          },
        },
        annotation: {
          annotations: hasSpill ? {
            spillBox: {
              type: "box",
              xMin: ts.time_minutes[firstSpillIdx],
              xMax: ts.time_minutes[lastSpillIdx],
              backgroundColor: "rgba(220, 38, 38, 0.08)",
              borderColor: "rgba(220, 38, 38, 0.3)",
              borderWidth: 1,
              label: {
                display: true,
                content: "SPILL",
                position: "start",
                color: "#dc2626",
                font: { size: 11, weight: "bold" },
              },
            },
          } : {},
        },
      },
      scales: {
        x: {
          type: "logarithmic",
          title: { display: true, text: "Time" },
          min: 0.1,
          ticks: {
            callback: function(val) {
              if (val < 1) return "0";
              if (val < 60) return Math.round(val) + " min";
              if (val < 1440) {
                const h = val / 60;
                return (h % 1 === 0 ? h : h.toFixed(1)) + " hr";
              }
              const d = val / 1440;
              return (d % 1 === 0 ? d : d.toFixed(1)) + " d";
            },
            autoSkip: false,
            maxRotation: 45,
            minRotation: 0,
          },
          afterBuildTicks: function(axis) {
            const maxMin = axis.max;
            let ticks = [{ value: 0.1 }];
            // Minutes
            for (const t of [1, 2, 5, 10, 15, 30]) {
              if (t <= maxMin) ticks.push({ value: t });
            }
            // Hours
            for (const h of [1, 2, 3, 6, 12]) {
              const m = h * 60;
              if (m <= maxMin) ticks.push({ value: m });
            }
            // Days
            for (const d of [1, 2, 3, 5, 7, 14]) {
              const m = d * 1440;
              if (m <= maxMin) ticks.push({ value: m });
            }
            axis.ticks = ticks;
          },
        },
        y: {
          type: "linear",
          position: "left",
          title: { display: true, text: "Volume (m³)" },
          beginAtZero: true,
        },
        y2: {
          type: "linear",
          position: "right",
          title: { display: true, text: "Depth (m)" },
          beginAtZero: true,
          grid: { drawOnChartArea: false },
        },
      },
    },
  });
  chartInstances.push(chart);
}

// --- LGA Boundaries ---
const lgaPopupData = {
  "CITY OF VINCENT": {
    spec: "Requires full onsite retention. Rights of Way standards mandate a 1.2m x 1.2m soakwell per 100m² of paved area, or 0.9m x 0.9m per 45m².",
    link: "https://www.vincent.wa.gov.au/your-home/property/my-property.aspx"
  },
  "CITY OF NEDLANDS": {
    spec: "1% AEP (1 in 100-year ARI). Requires an 8.0m/day infiltration coefficient and a 0.9 runoff coefficient. Evaluated via City XLS tool.",
    link: "https://www.nedlands.wa.gov.au/documents/865/city-of-nedlands-soakwell-capacity-calculator"
  },
  "CITY OF MELVILLE": {
    spec: "1% AEP for commercial/large sites; 5% AEP (1 in 20-year ARI) for standard residential.",
    link: "https://www.melvillecity.com.au/stormwater-calculator"
  },
  "CITY OF CANNING": {
    spec: "5% AEP with an overland flow path (Vol = Area x 0.0150); 1% AEP with no flow path. Max site discharge of 4 L/s if connecting to City drains.",
    link: "https://www.canning.wa.gov.au/media/d2gnyokv/stormwater-drainage-information-sheet.pdf"
  },
  "CITY OF COCKBURN": {
    spec: "1% AEP 24h storm event. Storage Volume = 1460 x Equivalent Impervious Area (ha).",
    link: "https://www.cockburn.wa.gov.au/getattachment/5fe5038e-bfcc-4b61-9a66-94b8644edf90/ECM_8683707_v1_Onsite-Drainage-Requirements-Industrial-and-Commercial-Lots-Guidelines-pdf.aspx"
  },
  "CITY OF GOSNELLS": {
    spec: "5% AEP for infill development with an overland flow path to the street; 1% AEP otherwise.",
    link: "https://www.gosnells.wa.gov.au/Building_and_development/Engineering/Stormwater_and_drainage/How_to_Use_the_Stormwater_Design_Calculator"
  },
  "CITY OF KALAMUNDA": {
    spec: "5% AEP if lot levels are above the road level; 1% AEP if below. Requires site-specific geotechnical data for hydraulic conductivity.",
    link: "https://www.kalamunda.wa.gov.au/docs/default-source/engineering/stormwater-design-guidelines-for-subdivisional-and-property-development-v2.pdf"
  },
  "CITY OF JOONDALUP": {
    spec: "Prescriptive tables based on surface area (e.g., one 1.2m x 1.2m soakwell per 111m² of surface drained).",
    link: "https://www.joondalup.wa.gov.au/plan-and-build/residential-building-and-renovation-guides/residential-soakwells-(stormwater-runoff)"
  },
  "CITY OF STIRLING": {
    spec: "Minimum 900mm x 600mm for roof water. Roof runoff must be stored and infiltrated entirely separately from surface runoff.",
    link: "https://www.stirling.wa.gov.au/awcontent/Web/Documents/Developing%20Property/Building%20documents/City-of-Stirling-On-Site-Drainage-Criteria-June-2024-1.pdf"
  },
  "CITY OF SWAN": {
    spec: "Density and land-use dependent volumetric tables factoring in clay vs. sand soil sites.",
    link: "https://www.swan.wa.gov.au/soakwell-specs"
  },
  "TOWN OF EAST FREMANTLE": {
    spec: "Tabular specifications scaling linearly with the total impervious area (m²).",
    link: "https://www.eastfremantle.wa.gov.au/drainage-specs"
  },
  "CITY OF WANNEROO": {
    spec: "Standard 5% AEP (1:20 ARI) calculation for sandy residential areas.",
    link: "https://www.wanneroo.wa.gov.au/stormwater"
  },
  "CITY OF SOUTH PERTH": {
    spec: "Segregated by specific \"Drainage Precincts\" dictating differing baseline retention requirements.",
    link: "https://southperth.wa.gov.au/stormwater-guidelines"
  }
};

let lgaGeoJsonLayer = null;

function toTitleCase(str) {
  if (!str) return "";
  return str.toLowerCase().split(' ').map(word => {
    if (word.startsWith('(') && word.endsWith(')')) {
      return word;
    }
    return word.charAt(0).toUpperCase() + word.slice(1);
  }).join(' ');
}

function updateLgaWarning() {
  if (!lgaGeoJsonLayer) return;

  const warningBox = document.getElementById("lga-warning-box");
  const intersectingLayers = leafletPip.pointInLayer(marker.getLatLng(), lgaGeoJsonLayer, false);

  if (intersectingLayers.length > 0) {
    const feature = intersectingLayers[0].feature;
    const geojsonLgaName = feature.properties.name || "";
    const nameParts = geojsonLgaName.split(', ');
    const simplifiedName = (nameParts.length === 2 ? `${nameParts[1]} ${nameParts[0]}` : geojsonLgaName).toUpperCase();

    if (lgaPopupData[simplifiedName]) {
      const popupData = lgaPopupData[simplifiedName];
      const displayName = toTitleCase(simplifiedName.replace(/,.*$/, ''));
      const warningContent = `
        <div class="card" style="background-color: #fffbe6; border-color: #facc15;">
          <h4 style="font-size:1.1rem;margin-bottom:.5rem;color:#ca8a04">⚠️ Local Government Area: ${displayName}</h4>
          <p style="font-size:.8rem"><strong>Sizing Formula / Design Specification:</strong><br/> ${popupData.spec}</p>
          <a href="${popupData.link}" target="_blank" style="font-size:.8rem">Official Resource / Tool</a>
          <p style="font-size:0.7rem; color: #666; margin-top: 0.5rem; border-top: 1px solid #eee; padding-top: 0.5rem;">
            <strong>Disclaimer:</strong> LGA guidelines are subject to change. Always verify requirements with the current official documentation from the relevant council.
          </p>
        </div>
      `;
      warningBox.innerHTML = warningContent;
      warningBox.style.display = "block";
      return;
    }
  }
  warningBox.style.display = "none";
  warningBox.innerHTML = "";
}

fetch('/static/LGA/LGATE_233_WA_GDA2020.geojson')
  .then(response => {
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    return response.json();
  })
  .then(data => {
    lgaGeoJsonLayer = L.geoJSON(data, {
      style: {
        color: "#4a5568",
        weight: 1,
        opacity: 0.5,
        fillOpacity: 0.1,
        interactive: false,
      },
    }).addTo(map);
    updateLgaWarning(); // Initial check
  })
  .catch(error => {
    console.error("Error loading LGA boundaries:", error);
  });




// ── Basin Graphic Renderer ───────────────────────────────────────────────
function renderBasinGraphic() {
    // Renders the interactive 2D section + plan (basim-section.js). Kept for
    // backward-compat with call sites that call renderBasinGraphic().
    if (typeof initSection2D === "function") {
      initSection2D();
      if (typeof attach2DInputListeners === "function") attach2DInputListeners();
      if (typeof updateSceneFromInputs === "function") updateSceneFromInputs();
    }
}

// Wire results into the 2D section: called after renderResults completes.
function renderResults3D(data) {
    if (typeof renderResults2D === "function") {
      renderResults2D(data);
    }
}
