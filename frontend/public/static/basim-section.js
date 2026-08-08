/**
 * basim-section.js — BaSIM Engine 2D Section + Plan (HTML5 Canvas)
 *
 * Replaces the former Three.js 3D geometric view. Renders two interactive,
 * live-updating 2D drawings of the basin:
 *
 *   Cross-section (long axis): trapezoidal excavation with batters, ground
 *     surface, invert, vadose (soil) zone, design groundwater level, saturated
 *     zone, base aquifer level, and any hydraulic structures at their levels.
 *   Plan (top-down): base footprint + top-of-batter outline + structures.
 *
 * Both drawings update live from the input fields BEFORE a run (design mode).
 * After a run, the section additionally shows the critical (peak) ponded water
 * level and the peak groundwater mound (static — no animation).
 *
 * Public API (kept function names used by app.js):
 *   initSection2D()            — set up canvases (idempotent)
 *   updateSceneFromInputs()    — redraw both drawings from current inputs
 *   attach2DInputListeners()   — live two-way binding on geometry/gw inputs
 *   renderResults2D(data)      — overlay peak water + mound from a run
 *   setDesign2D()              — clear results overlay (back to design mode)
 */

// ── Palette ────────────────────────────────────────────────────────────────
const SEC_SKY = "#f5f8fc";
const SEC_EARTH = "#dccaa6";
const SEC_EARTH_EDGE = "#a8895b";
const SEC_SAT = "rgba(37,99,235,0.14)";     // saturated zone tint
const SEC_GWL = "#2563eb";                    // groundwater level line
const SEC_WATER = "rgba(59,130,246,0.55)";   // ponded water
const SEC_WATER_EDGE = "#2563eb";
const SEC_MOUND = "rgba(96,165,250,0.45)";   // groundwater mound
const SEC_SURFACE = "#6b8e5a";                // ground surface line
const SEC_INK = "#334155";                    // basin outline / annotations
const SEC_MUTED = "#64748b";
const SEC_AQUIFER = "#8a6d3b";                // base aquifer line
const SEC_WEIR = "#8b4513";
const SEC_CULVERT = "#4b5563";
const SEC_PIT = "#374151";

// ── Module state ─────────────────────────────────────────────────────────
let _sec2dInitialised = false;
let _sec2dDesignMode = true;
let _sec2dPeakDepth = 0.0;   // peak ponded depth above invert (m)
let _sec2dPeakMound = 0.0;   // peak mound height above GWL (m)

// ── Input helpers ────────────────────────────────────────────────────────
function _s2num(id, fallback) {
  const el = document.getElementById(id);
  if (!el || el.value === "") return fallback;
  const v = parseFloat(el.value);
  return isNaN(v) ? fallback : v;
}

function _readGeometry() {
  const g = {
    baseLength: _s2num("inp-basin-length", 8),
    baseWidth: _s2num("inp-basin-width", 5),
    sideSlope: _s2num("inp-basin-side-slope", 4),   // 1:X (X horizontal per 1 vertical)
    maxDepth: _s2num("inp-basin-depth", 1.2),
    invertAHD: _s2num("inp-surface-lvl", 10.0),
    gwlAHD: _s2num("inp-design-gwl", 7.0),
    baseAquiferAHD: _s2num("inp-base-aquifer-lvl", 0.0),
  };
  g.surfaceAHD = g.invertAHD + g.maxDepth;
  g.topLength = g.baseLength + 2 * g.sideSlope * g.maxDepth;
  g.topWidth = g.baseWidth + 2 * g.sideSlope * g.maxDepth;
  return g;
}

function _getStructures() {
  if (typeof window._getBasimStructures === "function") {
    const enabled = document.getElementById("inp-structures-enabled");
    if (!enabled || !enabled.checked) return [];
    return window._getBasimStructures() || [];
  }
  return [];
}

// ── Canvas setup (DPR-aware) ──────────────────────────────────────────────
function _setupCanvas(canvas, cssHeight) {
  const dpr = window.devicePixelRatio || 1;
  const cssWidth = Math.max(240, Math.floor(canvas.getBoundingClientRect().width || canvas.clientWidth || 400));
  canvas.width = Math.floor(cssWidth * dpr);
  canvas.height = Math.floor(cssHeight * dpr);
  canvas.style.height = cssHeight + "px";
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, w: cssWidth, h: cssHeight };
}

// world (metres) → pixel transform at TRUE 1:1 scale (equal x/y metres-per-
// pixel, centred). No vertical exaggeration, so batter slopes are drawn at the
// exact side-slope entered by the user and the section is geometrically faithful.
function _makeTransform(w, h, xMin, xMax, yMin, yMax, pad) {
  const availW = Math.max(1, w - 2 * pad.l);
  const availH = Math.max(1, h - pad.t - pad.b);
  const spanX = Math.max(1e-6, xMax - xMin);
  const spanY = Math.max(1e-6, yMax - yMin);
  const s = Math.min(availW / spanX, availH / spanY);   // single scale for both axes
  const offL = pad.l + (availW - spanX * s) / 2;         // centre horizontally
  const offB = pad.b + (availH - spanY * s) / 2;         // centre vertically
  return {
    x: (x) => offL + (x - xMin) * s,
    y: (y) => h - offB - (y - yMin) * s,
    sx: s, sy: s,
  };
}

// ── Public: init ──────────────────────────────────────────────────────────
function initSection2D() {
  if (_sec2dInitialised) return;
  const sec = document.getElementById("section-canvas");
  const plan = document.getElementById("plan-canvas");
  if (!sec || !plan) return;
  _sec2dInitialised = true;
}

// ── Section drawing ────────────────────────────────────────────────────────
function _drawSection() {
  const canvas = document.getElementById("section-canvas");
  if (!canvas) return;
  const { ctx, w, h } = _setupCanvas(canvas, 320);
  const g = _readGeometry();

  // World extents: include base aquifer up to just above the ground surface.
  const halfTop = g.topLength / 2;
  const xMin = -halfTop - 2.0;
  const xMax = halfTop + 2.0;
  const yTopWorld = g.surfaceAHD + Math.max(0.4, g.maxDepth * 0.35);
  const yBotWorld = Math.min(g.baseAquiferAHD, g.gwlAHD - 0.3);
  const pad = { l: 54, t: 14, b: 26 };
  const T = _makeTransform(w, h, xMin, xMax, yBotWorld, yTopWorld, pad);

  // Background (sky / open air above ground)
  ctx.fillStyle = SEC_SKY;
  ctx.fillRect(0, 0, w, h);

  // Earth block (full width, from bottom up to the ground surface)
  ctx.fillStyle = SEC_EARTH;
  ctx.fillRect(T.x(xMin), T.y(g.surfaceAHD), T.x(xMax) - T.x(xMin), T.y(yBotWorld) - T.y(g.surfaceAHD));

  // Saturated zone tint (below GWL, full width)
  ctx.fillStyle = SEC_SAT;
  ctx.fillRect(T.x(xMin), T.y(g.gwlAHD), T.x(xMax) - T.x(xMin), T.y(yBotWorld) - T.y(g.gwlAHD));

  // Carve out the basin void (trapezoid) back to sky colour
  ctx.beginPath();
  ctx.moveTo(T.x(-g.baseLength / 2), T.y(g.invertAHD));
  ctx.lineTo(T.x(g.baseLength / 2), T.y(g.invertAHD));
  ctx.lineTo(T.x(halfTop), T.y(g.surfaceAHD));
  ctx.lineTo(T.x(-halfTop), T.y(g.surfaceAHD));
  ctx.closePath();
  ctx.fillStyle = SEC_SKY;
  ctx.fill();

  // Ground surface line
  ctx.strokeStyle = SEC_SURFACE;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(T.x(xMin), T.y(g.surfaceAHD));
  ctx.lineTo(T.x(-halfTop), T.y(g.surfaceAHD));
  ctx.moveTo(T.x(halfTop), T.y(g.surfaceAHD));
  ctx.lineTo(T.x(xMax), T.y(g.surfaceAHD));
  ctx.stroke();

  // ── Results overlay: ponded water (drawn inside the void, below surface) ──
  if (!_sec2dDesignMode && _sec2dPeakDepth > 0.001) {
    const wd = Math.min(_sec2dPeakDepth, g.maxDepth);
    const waterAHD = g.invertAHD + wd;
    const halfWaterTop = (g.baseLength + 2 * g.sideSlope * wd) / 2;
    ctx.beginPath();
    ctx.moveTo(T.x(-g.baseLength / 2), T.y(g.invertAHD));
    ctx.lineTo(T.x(g.baseLength / 2), T.y(g.invertAHD));
    ctx.lineTo(T.x(halfWaterTop), T.y(waterAHD));
    ctx.lineTo(T.x(-halfWaterTop), T.y(waterAHD));
    ctx.closePath();
    ctx.fillStyle = SEC_WATER;
    ctx.fill();
    ctx.strokeStyle = SEC_WATER_EDGE;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(T.x(-halfWaterTop), T.y(waterAHD));
    ctx.lineTo(T.x(halfWaterTop), T.y(waterAHD));
    ctx.stroke();
  }

  // Basin outline (batters + floor)
  ctx.strokeStyle = SEC_INK;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(T.x(-halfTop), T.y(g.surfaceAHD));
  ctx.lineTo(T.x(-g.baseLength / 2), T.y(g.invertAHD));
  ctx.lineTo(T.x(g.baseLength / 2), T.y(g.invertAHD));
  ctx.lineTo(T.x(halfTop), T.y(g.surfaceAHD));
  ctx.stroke();

  // ── Groundwater mound (results overlay) ──
  if (!_sec2dDesignMode && _sec2dPeakMound > 0.001) {
    const spread = Math.max(g.baseLength, 2.0) * 1.6;
    const peakAHD = g.gwlAHD + Math.min(_sec2dPeakMound, g.invertAHD - g.gwlAHD);
    ctx.beginPath();
    ctx.moveTo(T.x(-spread), T.y(g.gwlAHD));
    ctx.quadraticCurveTo(T.x(0), T.y(peakAHD + (peakAHD - g.gwlAHD)), T.x(spread), T.y(g.gwlAHD));
    ctx.closePath();
    ctx.fillStyle = SEC_MOUND;
    ctx.fill();
  }

  // Groundwater level line (full width)
  ctx.strokeStyle = SEC_GWL;
  ctx.lineWidth = 1.6;
  ctx.setLineDash([]);
  ctx.beginPath();
  ctx.moveTo(T.x(xMin), T.y(g.gwlAHD));
  ctx.lineTo(T.x(xMax), T.y(g.gwlAHD));
  ctx.stroke();
  _drawWaterTableTicks(ctx, T, xMin, xMax, g.gwlAHD);

  // Base aquifer line
  if (yBotWorld <= g.baseAquiferAHD + 1e-6) {
    ctx.strokeStyle = SEC_AQUIFER;
    ctx.lineWidth = 2;
    ctx.setLineDash([6, 3]);
    ctx.beginPath();
    ctx.moveTo(T.x(xMin), T.y(g.baseAquiferAHD));
    ctx.lineTo(T.x(xMax), T.y(g.baseAquiferAHD));
    ctx.stroke();
    ctx.setLineDash([]);
  }

  // Structures
  _drawSectionStructures(ctx, T, g);

  // Level annotations (right-hand gutter)
  ctx.font = "10px Inter, sans-serif";
  ctx.textBaseline = "middle";
  _levelLabel(ctx, T, w, g.surfaceAHD, `Ground ${g.surfaceAHD.toFixed(2)}`, SEC_SURFACE);
  _levelLabel(ctx, T, w, g.invertAHD, `Invert ${g.invertAHD.toFixed(2)}`, SEC_INK);
  _levelLabel(ctx, T, w, g.gwlAHD, `GWL ${g.gwlAHD.toFixed(2)}`, SEC_GWL);
  if (yBotWorld <= g.baseAquiferAHD + 1e-6) {
    _levelLabel(ctx, T, w, g.baseAquiferAHD, `Aquifer ${g.baseAquiferAHD.toFixed(2)}`, SEC_AQUIFER);
  }

  // Zone labels
  ctx.fillStyle = SEC_MUTED;
  ctx.textAlign = "center";
  const vadoseMidAHD = (g.invertAHD + g.gwlAHD) / 2;
  if (g.invertAHD - g.gwlAHD > 0.4) {
    ctx.fillText("Vadose zone", T.x(-halfTop - 1.0), T.y(vadoseMidAHD));
  }
  ctx.fillStyle = SEC_GWL;
  ctx.fillText("Saturated", T.x(-halfTop - 1.0), T.y(g.gwlAHD - Math.max(0.4, (g.gwlAHD - yBotWorld) * 0.35)));
  ctx.textAlign = "start";

  // Title + true-scale batter-slope note
  ctx.fillStyle = SEC_INK;
  ctx.font = "600 11px Inter, sans-serif";
  ctx.textBaseline = "top";
  ctx.fillText("Cross-section (long axis)", pad.l, 2);
  ctx.fillStyle = SEC_MUTED;
  ctx.font = "9px Inter, sans-serif";
  ctx.textAlign = "end";
  if (w >= 420) {
    ctx.fillText(`Batter 1:${g.sideSlope} (V:H) · true scale`, w - 6, 2);
  }
  ctx.textAlign = "start";
}

function _drawWaterTableTicks(ctx, T, xMin, xMax, gwlAHD) {
  // small downward ticks below the GWL line (standard water-table symbol)
  ctx.strokeStyle = SEC_GWL;
  ctx.lineWidth = 1;
  const y0 = T.y(gwlAHD);
  const step = (T.x(xMax) - T.x(xMin)) / 14;
  for (let px = T.x(xMin) + step; px < T.x(xMax); px += step) {
    ctx.beginPath();
    ctx.moveTo(px, y0);
    ctx.lineTo(px - 3, y0 + 4);
    ctx.stroke();
  }
}

function _levelLabel(ctx, T, w, ahd, text, color) {
  const py = T.y(ahd);
  ctx.fillStyle = color;
  ctx.textAlign = "end";
  ctx.fillText(text, w - 6, py);
  ctx.textAlign = "start";
  // leader tick
  ctx.strokeStyle = color;
  ctx.lineWidth = 0.75;
  ctx.beginPath();
  ctx.moveTo(w - 52, py);
  ctx.lineTo(w - 46, py);
  ctx.stroke();
}

function _drawSectionStructures(ctx, T, g) {
  const structures = _getStructures();
  if (!structures.length) return;
  const halfTop = g.topLength / 2;

  structures.forEach((s, i) => {
    if (s.type === "weir") {
      const crest = s.weir_crest_level_m_ahd != null ? s.weir_crest_level_m_ahd : g.surfaceAHD - 0.2;
      // crest overflow line across the basin + a block at the right edge
      ctx.strokeStyle = SEC_WEIR;
      ctx.lineWidth = 1.5;
      ctx.setLineDash([4, 3]);
      ctx.beginPath();
      ctx.moveTo(T.x(-g.baseLength / 2), T.y(crest));
      ctx.lineTo(T.x(g.baseLength / 2), T.y(crest));
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = SEC_WEIR;
      const bw = Math.max(4, 0.25 * T.sx);
      ctx.fillRect(T.x(g.baseLength / 2) - bw, T.y(crest), bw, T.y(g.invertAHD) - T.y(crest));
      _structLabel(ctx, T, g.baseLength / 2, crest, `Weir ${crest.toFixed(2)}`, SEC_WEIR, i);
    } else if (s.type === "culvert") {
      const inv = s.culvert_invert_level_m_ahd != null ? s.culvert_invert_level_m_ahd : g.invertAHD + 0.1;
      const dia = (s.culvert_diameter_mm || 450) / 1000.0;
      const cx = T.x(g.baseLength / 2 - 0.4);
      const cy = T.y(inv + dia / 2);
      const rx = Math.max(4, (dia / 2) * T.sx);
      const ry = Math.max(4, (dia / 2) * T.sy);
      ctx.strokeStyle = SEC_CULVERT;
      ctx.fillStyle = "rgba(75,85,99,0.25)";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      _structLabel(ctx, T, g.baseLength / 2 - 0.4, inv + dia, `Culvert ${inv.toFixed(2)}`, SEC_CULVERT, i);
    } else if (s.type === "grated_pit") {
      const inlet = s.pit_inlet_level_m_ahd != null ? s.pit_inlet_level_m_ahd : g.surfaceAHD - 0.3;
      const len = s.pit_length_m || 0.6;
      const halfL = (len / 2) * T.sx;
      ctx.fillStyle = SEC_PIT;
      // riser from invert to inlet
      ctx.fillRect(T.x(0) - Math.max(3, halfL), T.y(inlet), Math.max(6, halfL * 2), T.y(g.invertAHD) - T.y(inlet));
      // grate cap
      ctx.fillStyle = SEC_INK;
      ctx.fillRect(T.x(0) - Math.max(4, halfL + 1), T.y(inlet) - 2, Math.max(8, halfL * 2 + 2), 3);
      _structLabel(ctx, T, 0, inlet, `Pit ${inlet.toFixed(2)}`, SEC_PIT, i);
    }
  });
}

function _structLabel(ctx, T, xWorld, ahd, text, color, i) {
  ctx.fillStyle = color;
  ctx.font = "9px Inter, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "bottom";
  ctx.fillText(text, T.x(xWorld), T.y(ahd) - 4 - (i % 2) * 11);
  ctx.textAlign = "start";
  ctx.textBaseline = "middle";
}

// ── Plan drawing ────────────────────────────────────────────────────────────
function _drawPlan() {
  const canvas = document.getElementById("plan-canvas");
  if (!canvas) return;
  const { ctx, w, h } = _setupCanvas(canvas, 320);
  const g = _readGeometry();

  const halfTopL = g.topLength / 2;
  const halfTopW = g.topWidth / 2;
  const xMin = -halfTopL - 1.5;
  const xMax = halfTopL + 1.5;
  const yMin = -halfTopW - 1.5;
  const yMax = halfTopW + 1.5;
  const pad = { l: 18, t: 22, b: 26 };
  const T = _makeTransform(w, h, xMin, xMax, yMin, yMax, pad);

  ctx.fillStyle = SEC_SKY;
  ctx.fillRect(0, 0, w, h);

  // Batter zone (between top-of-batter and base) — earth tint
  ctx.fillStyle = "rgba(220,202,166,0.55)";
  ctx.fillRect(T.x(-halfTopL), T.y(halfTopW), (halfTopL * 2) * T.sx, (halfTopW * 2) * T.sy);

  // Base footprint (inner rectangle) — open basin floor
  ctx.fillStyle = "#eef4fb";
  ctx.fillRect(T.x(-g.baseLength / 2), T.y(g.baseWidth / 2),
    g.baseLength * T.sx, g.baseWidth * T.sy);

  // Water footprint at peak (results overlay)
  if (!_sec2dDesignMode && _sec2dPeakDepth > 0.001) {
    const wd = Math.min(_sec2dPeakDepth, g.maxDepth);
    const wl = g.baseLength + 2 * g.sideSlope * wd;
    const ww = g.baseWidth + 2 * g.sideSlope * wd;
    ctx.fillStyle = SEC_WATER;
    ctx.fillRect(T.x(-wl / 2), T.y(ww / 2), wl * T.sx, ww * T.sy);
  }

  // Top-of-batter outline (dashed)
  ctx.strokeStyle = SEC_EARTH_EDGE;
  ctx.lineWidth = 1.4;
  ctx.setLineDash([5, 3]);
  ctx.strokeRect(T.x(-halfTopL), T.y(halfTopW), (halfTopL * 2) * T.sx, (halfTopW * 2) * T.sy);
  ctx.setLineDash([]);

  // Base outline (solid)
  ctx.strokeStyle = SEC_INK;
  ctx.lineWidth = 2;
  ctx.strokeRect(T.x(-g.baseLength / 2), T.y(g.baseWidth / 2), g.baseLength * T.sx, g.baseWidth * T.sy);

  // Structures in plan
  _drawPlanStructures(ctx, T, g);

  // Dimension labels
  ctx.fillStyle = SEC_INK;
  ctx.font = "10px Inter, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  ctx.fillText(`Base L = ${g.baseLength.toFixed(1)} m`, T.x(0), T.y(-g.baseWidth / 2) + 3);
  ctx.save();
  ctx.translate(T.x(-g.baseLength / 2) - 4, T.y(0));
  ctx.rotate(-Math.PI / 2);
  ctx.textBaseline = "bottom";
  ctx.fillText(`Base W = ${g.baseWidth.toFixed(1)} m`, 0, 0);
  ctx.restore();

  ctx.fillStyle = SEC_MUTED;
  ctx.font = "9px Inter, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "bottom";
  ctx.fillText(`Top of batter ${g.topLength.toFixed(1)} × ${g.topWidth.toFixed(1)} m`, T.x(0), T.y(halfTopW) - 2);

  // Title + north arrow
  ctx.fillStyle = SEC_INK;
  ctx.font = "600 11px Inter, sans-serif";
  ctx.textAlign = "start";
  ctx.textBaseline = "top";
  ctx.fillText("Plan (top-down)", pad.l, 2);
  _drawNorthArrow(ctx, w - 20, 30);
}

function _drawPlanStructures(ctx, T, g) {
  const structures = _getStructures();
  if (!structures.length) return;
  const xEdge = g.baseLength / 2;

  structures.forEach((s) => {
    if (s.type === "weir") {
      const len = s.weir_length_m || 2.0;
      ctx.strokeStyle = SEC_WEIR;
      ctx.lineWidth = 4;
      ctx.beginPath();
      ctx.moveTo(T.x(xEdge), T.y(-len / 2));
      ctx.lineTo(T.x(xEdge), T.y(len / 2));
      ctx.stroke();
    } else if (s.type === "culvert") {
      const dia = (s.culvert_diameter_mm || 450) / 1000.0;
      ctx.strokeStyle = SEC_CULVERT;
      ctx.lineWidth = Math.max(3, dia * T.sy);
      ctx.beginPath();
      ctx.moveTo(T.x(xEdge - 0.4), T.y(0));
      ctx.lineTo(T.x(g.topLength / 2 + 1.0), T.y(0));
      ctx.stroke();
    } else if (s.type === "grated_pit") {
      const len = s.pit_length_m || 0.6;
      const wid = s.pit_width_m || 0.6;
      ctx.fillStyle = SEC_PIT;
      ctx.fillRect(T.x(-len / 2), T.y(wid / 2), len * T.sx, wid * T.sy);
    }
  });
}

function _drawNorthArrow(ctx, cx, cy) {
  ctx.save();
  ctx.strokeStyle = SEC_INK;
  ctx.fillStyle = SEC_INK;
  ctx.lineWidth = 1.2;
  ctx.beginPath();
  ctx.moveTo(cx, cy - 10);
  ctx.lineTo(cx - 5, cy + 6);
  ctx.lineTo(cx, cy + 2);
  ctx.lineTo(cx + 5, cy + 6);
  ctx.closePath();
  ctx.fill();
  ctx.font = "9px Inter, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  ctx.fillText("N", cx, cy + 7);
  ctx.restore();
}

// ── Public API ────────────────────────────────────────────────────────────
function updateSceneFromInputs() {
  if (!_sec2dInitialised) initSection2D();
  try {
    _drawSection();
    _drawPlan();
  } catch (e) {
    console.warn("2D section/plan draw failed:", e);
  }
}

function setDesign2D() {
  _sec2dDesignMode = true;
  _sec2dPeakDepth = 0.0;
  _sec2dPeakMound = 0.0;
  updateSceneFromInputs();
}

function renderResults2D(data) {
  try {
    const runs = data && data.model_runs ? data.model_runs : [];
    if (runs.length && runs[0].depth_summary) {
      _sec2dPeakDepth = runs[0].depth_summary.peak_depth_m || 0.0;
      _sec2dPeakMound = runs[0].depth_summary.peak_mound_height_m || 0.0;
      _sec2dDesignMode = false;
    }
  } catch (e) {
    console.warn("renderResults2D:", e);
  }
  updateSceneFromInputs();
}

function attach2DInputListeners() {
  const ids = [
    "inp-basin-length", "inp-basin-width", "inp-basin-side-slope",
    "inp-basin-depth", "inp-surface-lvl", "inp-design-gwl", "inp-base-aquifer-lvl",
  ];
  ids.forEach((id) => {
    const el = document.getElementById(id);
    if (el && !el._sec2dBound) {
      el.addEventListener("input", () => updateSceneFromInputs());
      el._sec2dBound = true;
    }
  });
}

// Export to global scope (plain script, no module system)
window.initSection2D = initSection2D;
window.updateSceneFromInputs = updateSceneFromInputs;
window.attach2DInputListeners = attach2DInputListeners;
window.renderResults2D = renderResults2D;
window.setDesign2D = setDesign2D;

// Self-initialise on load so the preview is live BEFORE the first run.
document.addEventListener("DOMContentLoaded", () => {
  initSection2D();
  attach2DInputListeners();
  updateSceneFromInputs();
});
window.addEventListener("resize", () => {
  if (_sec2dInitialised) updateSceneFromInputs();
});
