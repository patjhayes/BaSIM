/* ── SoakSIM Dashboard — frontend logic ─────────────────────────────── */

// ── Supabase Auth ──────────────────────────────────────────────────────
const SUPABASE_URL = 'https://rwtpoehohxbtobxrmedi.supabase.co';
const SUPABASE_KEY = 'sb_publishable_p6Vn56YyXff8z06PPZ213Q_ccLXPows';
const supabaseClient = window.supabase.createClient(SUPABASE_URL, SUPABASE_KEY);

// ── Timed login gate ───────────────────────────────────────────────────
// Allow 60 seconds of anonymous use, then require login.
let _isLoggedIn = false;
let _loginGateActive = false;

// On load: check session & start timer if anonymous
supabaseClient.auth.getSession().then(({ data: { session } }) => {
  _isLoggedIn = !!session;
  _updateAuthUI();
  if (!session) {
    setTimeout(_activateLoginGate, 60_000); // 1 minute
  }
});

function _updateAuthUI() {
  const authLink = document.getElementById('auth-link');
  if (!authLink) return;
  if (_isLoggedIn) {
    authLink.textContent = 'Logout';
    authLink.style.color = '#ef4444';
    authLink.onclick = (e) => { e.preventDefault(); logout(); };
  } else {
    authLink.textContent = 'Login';
    authLink.style.color = 'var(--primary)';
    authLink.onclick = (e) => { e.preventDefault(); _showLoginModal(); };
  }
}

function _activateLoginGate() {
  if (_isLoggedIn) return; // logged in before timer expired
  _loginGateActive = true;
  _showLoginModal();
}

function _showLoginModal() {
  // Don't duplicate
  if (document.getElementById('login-gate-modal')) return;
  const overlay = document.createElement('div');
  overlay.id = 'login-gate-modal';
  overlay.style.cssText =
    'position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:10000;display:flex;align-items:center;justify-content:center;';
  overlay.innerHTML = `
    <div style="background:#fff;border-radius:12px;padding:2rem 2.5rem;max-width:400px;width:90%;box-shadow:0 8px 30px rgba(0,0,0,.25);text-align:center;font-family:Inter,sans-serif">
      <h2 style="margin:0 0 .5rem;font-size:1.3rem;color:#1e293b">Sign in to continue</h2>
      <p style="color:#64748b;font-size:.92rem;margin-bottom:1.5rem">
        Create a free account or sign in to keep using SoakSIM.
      </p>
      <div id="login-gate-msg" style="color:#ef4444;font-size:.85rem;min-height:1.2rem;margin-bottom:.5rem"></div>
      <input id="login-gate-email" type="email" placeholder="Email" style="width:100%;padding:.55rem .75rem;margin-bottom:.6rem;border:1px solid #cbd5e1;border-radius:6px;font-size:.95rem" />
      <input id="login-gate-pass" type="password" placeholder="Password" style="width:100%;padding:.55rem .75rem;margin-bottom:1rem;border:1px solid #cbd5e1;border-radius:6px;font-size:.95rem" />
      <button id="login-gate-forgot" style="width:100%;padding:0;background:none;border:none;color:var(--primary,#2563eb);font-size:.9rem;cursor:pointer;text-align:right;margin:-.5rem 0 1rem">
        Forgot password?
      </button>
      <button id="login-gate-signin" style="width:100%;padding:.6rem;background:var(--primary,#2563eb);color:#fff;border:none;border-radius:6px;font-size:.95rem;cursor:pointer;margin-bottom:.5rem">
        Sign In
      </button>
      <button id="login-gate-signup" style="width:100%;padding:.6rem;background:transparent;color:var(--primary,#2563eb);border:1px solid var(--primary,#2563eb);border-radius:6px;font-size:.95rem;cursor:pointer">
        Create Account
      </button>
    </div>`;
  document.body.appendChild(overlay);

  document.getElementById('login-gate-signin').onclick = async () => {
    const email = document.getElementById('login-gate-email').value.trim();
    const pass  = document.getElementById('login-gate-pass').value;
    const msg   = document.getElementById('login-gate-msg');
    msg.textContent = '';
    const { error } = await supabaseClient.auth.signInWithPassword({ email, password: pass });
    if (error) { msg.textContent = error.message; return; }
    _onLoginSuccess();
  };

  document.getElementById('login-gate-signup').onclick = async () => {
    const email = document.getElementById('login-gate-email').value.trim();
    const pass  = document.getElementById('login-gate-pass').value;
    const msg   = document.getElementById('login-gate-msg');
    msg.textContent = '';
    const { error } = await supabaseClient.auth.signUp({ email, password: pass });
    if (error) { msg.textContent = error.message; return; }
    msg.style.color = '#16a34a';
    msg.textContent = 'Check your email for a confirmation link.';
  };

  document.getElementById('login-gate-forgot').onclick = async () => {
    const email = document.getElementById('login-gate-email').value.trim();
    const msg = document.getElementById('login-gate-msg');
    msg.style.color = '#ef4444';
    msg.textContent = '';
    if (!email) {
      msg.textContent = 'Enter your email first to reset your password.';
      return;
    }
    const { error } = await supabaseClient.auth.resetPasswordForEmail(email, {
      redirectTo: `${window.location.origin}/login`,
    });
    if (error) {
      msg.textContent = error.message;
      return;
    }
    msg.style.color = '#16a34a';
    msg.textContent = 'Password reset email sent. Check your inbox.';
  };
}

function _onLoginSuccess() {
  _isLoggedIn = true;
  _loginGateActive = false;
  const modal = document.getElementById('login-gate-modal');
  if (modal) modal.remove();
  _updateAuthUI();
}

// Helper: retrieve the current access token for authenticated API calls
async function getAccessToken() {
  const { data: { session } } = await supabaseClient.auth.getSession();
  return session?.access_token || null;
}

// Logout: called from the header link
function logout() {
  supabaseClient.auth.signOut().then(() => {
    _isLoggedIn = false;
    _loginGateActive = true;
    _updateAuthUI();
    _showLoginModal();
  });
}

    let simulationData = null;

    // ── Map setup ───────────────────────────────────────────────────────────
    const map = L.map("map").setView([-31.9505, 115.8605], 11);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(map);

    let marker = L.marker([-31.9505, 115.8605], { draggable: true }).addTo(map);

    marker.on("dragend", () => {
      const { lat, lng } = marker.getLatLng();
      document.getElementById("inp-lat").value = lat.toFixed(5);
      document.getElementById("inp-lng").value = lng.toFixed(5);
      updateLgaWarning();
    });

    map.on("click", (e) => {
      marker.setLatLng(e.latlng);
      document.getElementById("inp-lat").value = e.latlng.lat.toFixed(5);
      document.getElementById("inp-lng").value = e.latlng.lng.toFixed(5);
      updateLgaWarning();
    });

    // ── Climate change scenario toggle ──────────────────────────────────
    document.getElementById("inp-cc-scenario").addEventListener("change", () => {
      const sel = document.getElementById("inp-cc-scenario").value;
      const epochField = document.getElementById("cc-epoch-field");
      const infoEl = document.getElementById("cc-info");
      if (sel === "Historical") {
        epochField.style.display = "none";
        infoEl.innerHTML = '<em>(i) Historical — only to be used for historical assessments</em>';
      } else {
        epochField.style.display = "";
        infoEl.innerHTML = `<em>Rainfall adjusted for ${sel} at chosen planning horizon (ARR 2019)</em>`;
      }
    });

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
            <p style="font-size:.72rem;margin:.4rem 0 .2rem;color:#666;font-weight:600">Flow Path Parameters (Kinematic Wave — Ragan & Duru Eq)</p>
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

const DEFAULT_SOAKWELL_SIZE = "1200 x 1200";
let soakwellSizes = [DEFAULT_SOAKWELL_SIZE];
var soakwellConfig = [{ size_name: DEFAULT_SOAKWELL_SIZE, count: 2 }];

function normalizeSoakwellConfig() {
  const fallbackSize = soakwellSizes[0] || DEFAULT_SOAKWELL_SIZE;
  soakwellConfig = soakwellConfig.map((sc) => ({
    ...sc,
    size_name: soakwellSizes.includes(sc.size_name) ? sc.size_name : fallbackSize,
  }));
}

async function loadSoakwellSizes() {
  try {
    const resp = await fetch("/api/catalogue");
    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}`);
    }
    const items = await resp.json();
    const names = items.map((item) => item.name).filter(Boolean);
    if (names.length > 0) {
      soakwellSizes = names;
      normalizeSoakwellConfig();
    }
  } catch (err) {
    console.warn("Failed to load soakwell catalogue", err);
  }
  renderSoakwellConfig();
}

function renderSoakwellConfig() {
  const list = document.getElementById("soakwell-config-list");
  list.innerHTML = "";
  soakwellConfig.forEach((sc, i) => {
    const div = document.createElement("div");
    div.className = "row";
    div.style.marginBottom = ".3rem";
    div.innerHTML = `
      <div class="field" style="flex:2">
        <label style="font-size:.72rem">Size (dia × depth mm)</label>
        <select onchange="soakwellConfig[${i}].size_name=this.value">
          ${soakwellSizes.map(s => `<option value="${s}" ${sc.size_name===s?"selected":""}>${s}</option>`).join("")}
        </select>
      </div>
      <div class="field" style="flex:1">
        <label style="font-size:.72rem">Count</label>
        <input type="number" value="${sc.count}" min="1" max="50" step="1"
               onchange="soakwellConfig[${i}].count=+this.value" />
      </div>
      ${soakwellConfig.length > 1 ? `<button class="remove-catch" onclick="removeSoakwellRow(${i})" style="margin-top:1rem">&times;</button>` : ""}
    `;
    list.appendChild(div);
  });
}
function addSoakwellRow() {
  soakwellConfig.push({ size_name: soakwellSizes[0] || DEFAULT_SOAKWELL_SIZE, count: 1 });
  renderSoakwellConfig();
}
function removeSoakwellRow(i) {
  soakwellConfig.splice(i, 1);
  renderSoakwellConfig();
}
loadSoakwellSizes();

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
  1, 2, 3, 4, 5, 10, 15, 20, 25, 30, 45,
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

// ── Run simulation ──────────────────────────────────────────────────────
async function runSimulation() {
  // ── Login gate check ──────────────────────────────────────────────────
  if (_loginGateActive && !_isLoggedIn) {
    _showLoginModal();
    return;
  }

  const btn = document.getElementById("btn-run");
  const loading = document.getElementById("loading");
  btn.disabled = true;
  loading.classList.add("active");

  const aepSelect = document.getElementById("inp-aeps");
  const selectedAEPs = Array.from(aepSelect.selectedOptions).map((o) => parseFloat(o.value));
  const durations = getSelectedDurations();
  // Design AEP = smallest selected AEP (most rare); pattern rank = median (4)
  const designAep = Math.min(...selectedAEPs);

  const soakwellConfigData = soakwellConfig;

  const body = {
    latitude: parseFloat(document.getElementById("inp-lat").value),
    longitude: parseFloat(document.getElementById("inp-lng").value),
    catchments: catchments,
    aep_percentages: selectedAEPs,
    durations_minutes: durations,
    infiltration_rate_mm_per_hr: parseFloat(document.getElementById("inp-infil").value) * 1000 / 24,
    design_drain_time_hours: parseFloat(document.getElementById("inp-drain").value),
    soil_moderation_factor: parseFloat(document.getElementById("inp-safety").value),
    pattern_rank: 4,
    design_aep_percent: designAep,
    soakwell_config: soakwellConfigData,
    use_live_data: true,
    climate_scenario: document.getElementById("inp-cc-scenario").value,
    climate_epoch: document.getElementById("inp-cc-scenario").value === "Historical"
      ? null
      : parseInt(document.getElementById("inp-cc-epoch").value),
  };

  const token = await getAccessToken();
  try {
    const resp = await fetch("/api/simulate", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { "Authorization": `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(body),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(err.detail || JSON.stringify(err));
    }

    const data = await resp.json();
    renderResults(data);
  } catch (e) {
    alert("Simulation failed:\n" + e.message);
  } finally {
    btn.disabled = false;
    loading.classList.remove("active");
  }
}

// ── Render results ───────────────────────────────────────────────────────
function renderResults(data) {
  simulationData = data;
  document.getElementById("placeholder").style.display = "none";
  document.getElementById("results-container").style.display = "block";
  destroyCharts();

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
    let configHTML = "";
    for (const [name, count] of Object.entries(d.configuration)) {
      configHTML += `<span class="config-tag">${count} × ${name}</span>`;
    }
    // Check for spill
    const spilled = data.soakwell_timeseries && data.soakwell_timeseries.spill_flag && data.soakwell_timeseries.spill_flag.some(f => f);
    const spillBadge = spilled
      ? `<div class="metric-card" style="border-color:#fca5a5;background:#fef2f2"><div class="value" style="color:#dc2626">SPILL</div><div class="label" style="color:#991b1b">Soakwell Overflows</div></div>`
      : `<div class="metric-card" style="border-color:#86efac;background:#f0fdf4"><div class="value" style="color:#166534">OK</div><div class="label" style="color:#166534">No Overflow</div></div>`;
    ds.innerHTML = `
      ${ccBadgeHTML}
      <div class="design-grid" style="margin-top:.8rem">
        <div class="metric-card">
          <div class="value">${d.required_storage_m3.toFixed(2)}</div>
          <div class="label">Required Storage (m³)</div>
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
      <h4 style="margin-top:1rem;font-size:.85rem;color:var(--primary)">Soakwell Configuration</h4>
      <div class="config-list">${configHTML}</div>
    `;
  } else {
    ds.innerHTML = `${ccBadgeHTML}<p style="color:var(--muted);padding:1rem">No soakwell design available.</p>`;
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

  // ── Hyetograph charts ───
  renderTimeSeriesCharts(
    "hyeto-charts",
    data.hyetographs,
    "Rainfall Depth (mm)",
    (h) => h.depths_mm,
    (h) => h.timestep_minutes,
    "bar"
  );

  // ── Cumulative volume charts ───
  renderCumulativeVolumeCharts(data.hydrographs);

  // ── Soakwell performance chart ───
  renderSoakwellPerformanceChart(data.soakwell_timeseries, data.soakwell_design);
}

function generateReport() {
    if (!simulationData) {
        alert("Please run a simulation first.");
        return;
    }

    const { project_name, soakwell_design, runoff_table } = simulationData;
    
    // ---- Get input data from the form ----
    const lat = parseFloat(document.getElementById("inp-lat").value);
    const lng = parseFloat(document.getElementById("inp-lng").value);
    const aeps = Array.from(document.getElementById("inp-aeps").selectedOptions).map(o => o.text).join(', ');
    const durations = getSelectedDurations().join(', ');
    const infiltration_rate = parseFloat(document.getElementById("inp-infil").value);
    const soil_moderation_factor = parseFloat(document.getElementById("inp-safety").value);
    

    // ---- Build HTML for the report ----
    let reportHtml = `
        <html>
        <head>
            <title>SoakSIM Simulation Report</title>
            <style>
                body { font-family: Inter, sans-serif; padding: 20px; }
                h1, h2, h3, h4 { color: #1a6b4f; }
                table { border-collapse: collapse; width: 100%; margin-top: 20px; }
                th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
                th { background-color: #f2f2f2; }
            </style>
        </head>
        <body>
            <h1>SoakSIM Simulation Report</h1>
            <h2>${project_name}</h2>
            
            <h3>Input Parameters</h3>
            <h4>Site Location</h4>
            <p><strong>Latitude:</strong> ${lat}</p>
            <p><strong>Longitude:</strong> ${lng}</p>

            <h4>Storm Settings</h4>
            <p><strong>AEPs:</strong> ${aeps}</p>
            <p><strong>Durations (min):</strong> ${durations}</p>

            <h4>Soil & Design Parameters</h4>
            <p><strong>Infiltration Rate:</strong> ${infiltration_rate} m/day</p>
            <p><strong>Soil Moderation Factor (U):</strong> ${soil_moderation_factor}</p>
            
            <h3>Catchment Details</h3>
    `;

    catchments.forEach((c, i) => {
        reportHtml += `<h4>Catchment ${i + 1}: ${c.name}</h4>
                        <p><strong>Area:</strong> ${c.area_ha} ha</p>
                        <p><strong>Paved:</strong> ${c.paved_fraction * 100}%, <strong>Supplementary:</strong> ${c.supplementary_fraction * 100}%, <strong>Grassed:</strong> ${c.grassed_fraction * 100}%</p>`;
    });

    if (soakwell_design) {
        reportHtml += `
            <h3>Results: Soakwell Design</h3>
            <p><strong>Design AEP:</strong> ${soakwell_design.aep}</p>
            <p><strong>Critical Duration:</strong> ${soakwell_design.critical_duration_minutes} min</p>
            <p><strong>Required Storage:</strong> ${soakwell_design.required_storage_m3} m³</p>
            <p><strong>Provided Configuration:</strong> ${Object.entries(soakwell_design.configuration).map(([name, count]) => `${count} × ${name}`).join(', ')}</p>
            <p><strong>Residual Storage:</strong> ${soakwell_design.residual_storage_m3} m³</p>
            <p><strong>Drain Time:</strong> ${soakwell_design.drain_time_hours} hours</p>
        `;
    }



    if (runoff_table && runoff_table.length > 0) {
        reportHtml += `
            <h3>Results: Runoff Table</h3>
            <table>
                <thead>
                    <tr>
                        <th>AEP</th>
                        <th>Duration (min)</th>
                        <th>Pattern Rank</th>
                        <th>Peak Flow (m³/s)</th>
                        <th>Volume (m³)</th>
                        <th>Time to Peak (min)</th>
                    </tr>
                </thead>
                <tbody>
        `;
        runoff_table.forEach(row => {
            reportHtml += `
                <tr>
                    <td>${row.aep}</td>
                    <td>${row.duration_minutes}</td>
                    <td>${row.pattern_rank}</td>
                    <td>${row.peak_discharge_cms.toFixed(4)}</td>
                    <td>${row.runoff_volume_m3.toFixed(2)}</td>
                    <td>${row.time_to_peak_minutes.toFixed(1)}</td>
                </tr>
            `;
        });
        reportHtml += `
                </tbody>
            </table>
        `;
    }

    reportHtml += `
        </body>
        </html>
    `;

    const reportWindow = window.open("", "_blank");
    reportWindow.document.write(reportHtml);
    reportWindow.document.close();
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
function renderSoakwellPerformanceChart(ts, design) {
  const container = document.getElementById("soakperf-charts");
  container.innerHTML = "";
  if (!ts || !ts.time_minutes || !ts.time_minutes.length) {
    container.innerHTML = `<p style="color:var(--muted);padding:1rem">No soakwell time-series data available. Run a simulation first.</p>`;
    return;
  }

  // Build chart title with critical storm details
  let chartTitle = "Soakwell Performance";
  if (design) {
    chartTitle = `Soakwell Performance \u2014 Critical Storm: ${design.critical_duration_minutes} min duration, Temporal Pattern #${design.selected_pattern_rank}`;
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
    banner.innerHTML = `⚠ SOAKWELL SPILL detected from t = ${spillStart} min to t = ${spillEnd} min — max surface ponding volume: ${maxOverflow.toFixed(3)} m³`;
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


