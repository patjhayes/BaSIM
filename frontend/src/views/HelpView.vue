<template>
  <div class="h-full bg-gray-50 flex flex-col p-6 overflow-y-auto">
    <div class="max-w-4xl mx-auto bg-white rounded-xl shadow-sm border border-gray-200 p-8">
      <h1 class="text-3xl font-bold text-gray-900 mb-2">Help & Documentation</h1>
      <p class="text-gray-600 mb-8 border-b pb-4">Your complete guide to using BaSIM and understanding the physics powering it.</p>

      <div class="space-y-12">

        <!-- PART 1: USER GUIDE -->
        <div>
          <h2 class="text-2xl font-bold text-gray-900 mb-6 bg-gray-100 p-3 rounded-md">Part 1: Step-by-Step User Guide</h2>
          
          <section class="mb-8">
            <h3 class="text-xl font-semibold text-blue-800 mb-3 border-b pb-2">
              1. Project Details
            </h3>
            <div class="prose prose-sm text-gray-700 max-w-none">
              <p>This section defines the metadata and billing information for your simulation.</p>
              <ul class="list-disc pl-5 space-y-1 mt-2 mb-4">
                <li><strong>Project Code (Required):</strong> A unique identifier used to track usage and deduct credits for commercial users (e.g., <code>PRJ-2026-001</code>). Government users (<code>.gov.au</code>) can leave this blank if running locally.</li>
                <li><strong>Project Name:</strong> A human-readable name for your project (e.g., <code>Oakwood Subdivision</code>). This appears on the final engineering report.</li>
                <li><strong>Scenario Name:</strong> A description of the specific simulation (e.g., <code>Pre-Development Base Case</code> or <code>1% AEP Design</code>).</li>
              </ul>
            </div>
          </section>

          <section class="mb-8">
            <h3 class="text-xl font-semibold text-blue-800 mb-3 border-b pb-2">
              2. Inflow Data Source
            </h3>
            <div class="prose prose-sm text-gray-700 max-w-none">
              <p>You must choose how stormwater enters the basin. BaSIM offers two methods: <strong>ILSAX</strong> (Internal Hydrological Routing) or <strong>TS1</strong> (External Hydrograph Upload).</p>
              
              <h4 class="text-md font-semibold mt-4 mb-2 text-gray-800">Option A: ILSAX</h4>
              <p>Selecting ILSAX allows BaSIM to automatically generate design storms using Australian Rainfall and Runoff (ARR) 2019 guidelines and route them over a defined catchment.</p>
              <ol class="list-decimal pl-5 space-y-2 mt-2">
                <li><strong>Map Location Picker:</strong> Click on the interactive map to select the exact location of your site. This automatically populates the Latitude and Longitude.</li>
                <li><strong>Fetch Climate Data Button:</strong> Click this to pull the latest Intensity-Frequency-Duration (IFD) data from the Bureau of Meteorology (BOM) and Temporal Patterns from the ARR Data Hub.</li>
                <li><strong>AEP (%):</strong> Select the Annual Exceedance Probability (e.g., <code>1%</code> for a 1-in-100 year storm).</li>
                <li><strong>Climate Scenario & Projection Year:</strong> Choose <code>Historic</code> for current conditions, or select an IPCC Shared Socioeconomic Pathway (e.g., <code>SSP2-4.5</code>) and a future year (e.g., <code>2050</code>) to apply climate change factors to the rainfall.</li>
                <li><strong>Durations (min):</strong> Select the storm durations you want to run. BaSIM runs an ensemble of 10 temporal patterns for <em>each</em> selected duration to find the critical storm.</li>
              </ol>

              <h4 class="text-md font-semibold mt-4 mb-2 text-gray-800">Option B: TS1 File Upload</h4>
              <p>If you have already generated a hydrograph using external software (like DRAINS or XPSWMM), select this option.</p>
              <ul class="list-disc pl-5 space-y-1 mt-2 mb-4">
                <li><strong>Upload TS1 Hydrograph(s):</strong> Click to browse and upload one or multiple <code>.ts1</code> formatted text files. BaSIM will run a simulation for each uploaded file.</li>
              </ul>
            </div>
          </section>

          <section class="mb-8">
            <h3 class="text-xl font-semibold text-blue-800 mb-3 border-b pb-2">
              3. ILSAX Catchment Parameters
            </h3>
            <div class="prose prose-sm text-gray-700 max-w-none">
              <p>If you selected ILSAX, you must define the physical characteristics of the land draining into the basin.</p>
              <ul class="list-disc pl-5 space-y-1 mt-2 mb-4">
                <li><strong>Name:</strong> A label for the catchment.</li>
                <li><strong>Area (ha):</strong> Total area of the catchment in hectares.</li>
                <li><strong>Slope (m/m):</strong> The average slope of the catchment.</li>
                <li><strong>Surface Fractions:</strong> Define the proportion of the catchment (must sum to 1.0 or less):
                  <ul class="list-circle pl-5 mt-1">
                    <li><strong>Paved (DCIA):</strong> Directly Connected Impervious Area (e.g., roofs, roads).</li>
                    <li><strong>Supplementary:</strong> Indirectly connected impervious areas.</li>
                    <li><strong>Grassed:</strong> Pervious, vegetated areas.</li>
                  </ul>
                </li>
                <li><strong>Soil Type (1-4):</strong> <code>1</code>: Sand (High infiltration), <code>2</code>: Sandy Loam, <code>3</code>: Clay Loam, <code>4</code>: Clay (Low infiltration).</li>
                <li><strong>AMC (1-4):</strong> Antecedent Moisture Condition prior to the storm. <code>1</code> is completely dry; <code>4</code> is fully saturated.</li>
              </ul>
              <div class="bg-blue-50 border border-blue-100 p-4 rounded mt-4">
                <p class="text-sm font-semibold text-blue-900 mb-1">Tip: Flow Path Parameters</p>
                <p class="text-sm text-blue-800">Advanced users can tweak Kinematic Wave routing parameters (Additional time, Flow path length, Flow path slope, Retardance n*, and Depression Storage). The defaults are based on standard Australian urban design practices.</p>
              </div>
            </div>
          </section>

          <section class="mb-8">
            <h3 class="text-xl font-semibold text-blue-800 mb-3 border-b pb-2">
              4. Basin Geometry & Aquifer
            </h3>
            <div class="prose prose-sm text-gray-700 max-w-none">
              <p>This section defines the physical shape of the basin and the geological properties of the surrounding soil.</p>
              
              <h4 class="text-md font-semibold mt-4 mb-2 text-gray-800">Geometry Type</h4>
              <ul class="list-disc pl-5 space-y-1 mt-2 mb-4">
                <li><strong>Standard Rectangle:</strong> Define a simple basin using Length (m), Width (m), and Side Slope (1 in X).</li>
                <li><strong>Custom Shapefile (.zip):</strong> Upload a zipped shapefile containing <code>.shp</code>, <code>.shx</code>, and <code>.dbf</code> files representing a complex, irregular basin footprint.</li>
              </ul>

              <h4 class="text-md font-semibold mt-4 mb-2 text-gray-800">Elevations</h4>
              <ul class="list-disc pl-5 space-y-1 mt-2 mb-4">
                <li><strong>Floor Elev (m AHD):</strong> The absolute elevation of the bottom of the basin.</li>
                <li><strong>Max Depth (m):</strong> The maximum allowable depth of water before the basin overflows or fails.</li>
              </ul>

              <h4 class="text-md font-semibold mt-4 mb-2 text-gray-800">Aquifer Material</h4>
              <p>Select a preset soil type (e.g., Sand, Clay) to auto-populate the hydraulic properties, or choose <strong>Custom</strong> to enter them manually:</p>
              <ul class="list-disc pl-5 space-y-1 mt-2 mb-4">
                <li><strong>Aquifer Kh (m/day):</strong> Horizontal hydraulic conductivity (how fast water moves sideways).</li>
                <li><strong>Initial Head (m AHD):</strong> The starting elevation of the groundwater table before the storm begins. Must be strictly lower than or equal to the Floor Elev.</li>
              </ul>

              <div class="bg-red-50 border border-red-100 p-4 rounded mt-4">
                <p class="text-sm font-semibold text-red-900 mb-1">Important: Advanced Aquifer Parameters</p>
                <p class="text-sm text-red-800">Expand this section to tweak Vertical Conductivity (Kv), Specific Yield (Sy), Specific Storage (Ss), and the Aquifer Bottom elevation. These dictate how the groundwater mound shapes itself beneath the basin.</p>
              </div>
            </div>
          </section>

          <section class="mb-8">
            <h3 class="text-xl font-semibold text-blue-800 mb-3 border-b pb-2">
              5. Clogging Layer (Infiltration)
            </h3>
            <div class="prose prose-sm text-gray-700 max-w-none">
              <p>Infiltration basins degrade over time due to siltation and bio-fouling. BaSIM models this physically using a clogging layer on the basin floor.</p>
              <ul class="list-disc pl-5 space-y-1 mt-2 mb-4">
                <li><strong>Bed K (m/day):</strong> The hydraulic conductivity of the clogged sediment (usually much lower than the native aquifer, e.g., <code>0.01</code> m/day).</li>
                <li><strong>Thickness (m):</strong> The depth of the clogged sediment layer (e.g., <code>0.5</code> m).</li>
                <li><strong>Infiltration Mode:</strong>
                  <ul class="list-circle pl-5 mt-1">
                    <li><code>Vertical Only</code>: Water only escapes through the floor.</li>
                    <li><code>Full</code>: Water escapes through the floor and the side-walls (sidewalls use the native Aquifer Kh).</li>
                  </ul>
                </li>
                <li><strong>Initial Infiltration Approach (Slider):</strong>
                  <ul class="list-circle pl-5 mt-1">
                    <li><strong>Conservative (Saturated):</strong> Assumes the soil is already wet, ignoring capillary suction. Safer for design.</li>
                    <li><strong>Optimistic (Dry Soil):</strong> Includes capillary suction, pulling water into the soil faster at the start of the storm.</li>
                  </ul>
                </li>
              </ul>
            </div>
          </section>

          <section class="mb-8">
            <h3 class="text-xl font-semibold text-blue-800 mb-3 border-b pb-2">
              6. Hydraulic Outlets
            </h3>
            <div class="prose prose-sm text-gray-700 max-w-none">
              <p>Outlets allow water to escape the basin if it gets too full. You can add multiple outlets, or leave this empty for a 100% retention basin.</p>
              <p>Click <strong>+ Add Outlet</strong> and select a type:</p>
              <ul class="list-disc pl-5 space-y-1 mt-2 mb-4">
                <li><strong>Pipe / Culvert:</strong> Requires Diameter, Invert Elevation, Length, and Grade.</li>
                <li><strong>Broad Crested Weir:</strong> An overflow spillway. Requires Crest Width and Crest Elevation.</li>
                <li><strong>Grated Inlet:</strong> A drop-inlet pit. Requires Grate Area, Crest Elevation, and Perimeter.</li>
              </ul>
              <div class="bg-blue-50 border border-blue-100 p-4 rounded mt-4">
                <p class="text-sm text-blue-900 mb-1"><strong>Note:</strong> Ensure the <strong>Enabled</strong> checkbox is ticked for the outlet to be active during the simulation.</p>
              </div>
            </div>
          </section>

          <section class="mb-8">
            <h3 class="text-xl font-semibold text-blue-800 mb-3 border-b pb-2">
              7. Running the Simulation & Viewing Results
            </h3>
            <div class="prose prose-sm text-gray-700 max-w-none">
              <p>Once all parameters are set, click the blue <strong>Run Simulation</strong> button at the bottom of the left panel.</p>
              <p>The right panel will automatically switch to the <strong>Simulation Progress</strong> tab. If running an ILSAX ensemble, BaSIM will run 10 temporal patterns simultaneously. Wait for the progress bar to reach 100%.</p>
              <p>Once complete, the UI will display:</p>
              <ol class="list-decimal pl-5 space-y-2 mt-2">
                <li><strong>Interactive Charts:</strong> Showing the inflow hydrograph, basin stage (water level) over time, and infiltration rates.</li>
                <li><strong>Peak Groundwater Contours:</strong> A heatmap and cross-section showing exactly how far and how high the groundwater mound spread beneath the basin.</li>
                <li><strong>Engineering Report:</strong> Click the download button to generate a standardised, timestamped HTML report documenting all inputs, peak stages, and visual charts for submission to local councils or regulatory authorities.</li>
              </ol>
            </div>
          </section>
        </div>


        <!-- PART 2: TECHNICAL REFERENCE -->
        <div class="mt-16 border-t-2 border-gray-200 pt-8">
          <h2 class="text-2xl font-bold text-gray-900 mb-6 bg-gray-100 p-3 rounded-md">Part 2: Technical Reference</h2>
          
          <section class="mb-8">
            <h3 class="text-xl font-semibold text-blue-800 mb-3 border-b pb-2">
              1. The Core Engine
            </h3>
            <div class="prose prose-sm text-gray-700 max-w-none">
              <p>BaSIM is powered by <strong>MODFLOW-USG</strong> (Unstructured Grid), utilising the advanced Unconfined Upstream Weighting (UUF) formulation. This engine rigorously solves the 3D groundwater flow equation (Darcy's Law combined with mass conservation).</p>
              <p>Traditional drainage calculators often assume a fixed infiltration rate or use simplified analytical models (like the Hantush equation). BaSIM physically routes water through a dynamically generated unstructured mesh, accounting for:</p>
              <ul class="list-disc pl-5 space-y-1 mt-2 mb-4">
                <li>Groundwater mounding and lateral dispersion</li>
                <li>Aquifer boundaries and initial water table elevations</li>
                <li>Transient feedback (infiltration rates decrease as the groundwater mound rises to meet the basin floor)</li>
              </ul>
            </div>
          </section>

          <section class="mb-8">
            <h3 class="text-xl font-semibold text-blue-800 mb-3 border-b pb-2">
              2. Hydrology & Runoff Routing
            </h3>
            <div class="prose prose-sm text-gray-700 max-w-none">
              <p>BaSIM handles catchment hydrology through the proven <strong>ILSAX</strong> (Illawarra Area Simulator) routing methodology, or by accepting externally generated hydrographs (TS1 format).</p>
              
              <h4 class="text-md font-semibold mt-4 mb-2 text-gray-800">Rainfall & Temporal Patterns</h4>
              <p>When using the internal hydrology engine, BaSIM integrates directly with the Australian Rainfall and Runoff (ARR) Datahub. It automatically retrieves the <strong>Intensity-Frequency-Duration (IFD)</strong> data and the regional <strong>Temporal Patterns</strong> based on the provided coordinate location.</p>
              <p>The engine simulates the full ensemble of 10 temporal patterns for each duration to identify the critical storm event that produces the highest median peak water level in the basin.</p>

              <h4 class="text-md font-semibold mt-4 mb-2 text-gray-800">ILSAX Routing</h4>
              <p>The ILSAX method computes surface runoff by dividing the catchment into three distinct hydrologic components:</p>
              <ul class="list-disc pl-5 space-y-1 mt-2 mb-4">
                <li><strong>Paved (Directly Connected)</strong>: Impervious areas that drain directly to the basin.</li>
                <li><strong>Supplementary (Indirectly Connected)</strong>: Impervious areas that drain onto pervious areas before reaching the basin.</li>
                <li><strong>Grassed (Pervious)</strong>: Pervious areas where significant infiltration occurs before runoff is generated.</li>
              </ul>
              <p>Rainfall losses are applied using the Initial Loss / Continuing Loss (IL/CL) model for pervious areas, governed by the specified Antecedent Moisture Condition (AMC) and Soil Type.</p>
              <p>Runoff is routed to the basin using a Kinematic Wave approach, calculating the time of concentration based on overland flow path lengths, slopes, and surface roughness (Manning's n*).</p>
            </div>
          </section>

          <section class="mb-8">
            <h3 class="text-xl font-semibold text-blue-800 mb-3 border-b pb-2">
              3. Pseudo-Lake Architecture
            </h3>
            <div class="prose prose-sm text-gray-700 max-w-none">
              <p>To accurately simulate the filling and emptying of the infiltration basin without requiring external routing packages, BaSIM employs a "Pseudo-Lake" architecture.</p>
              <p>The basin itself is represented as the top layer (Layer 0) of the groundwater model. This layer is assigned:</p>
              <ul class="list-disc pl-5 space-y-1 mt-2 mb-4">
                <li><strong>Specific Yield (S<sub>y</sub>) = 1.0</strong>: Meaning it represents 100% void space (open water).</li>
                <li><strong>Hydraulic Conductivity (K) = 100 m/day</strong>: Creating instantaneous horizontal equilibration of the water level across the basin footprint.</li>
              </ul>
              <p>Surface runoff from the catchment is injected directly into this layer. The water then infiltrates downwards into the underlying aquifer layers governed by Darcy's Law.</p>
            </div>
          </section>

          <section class="mb-8">
            <h3 class="text-xl font-semibold text-blue-800 mb-3 border-b pb-2">
              4. The Effective K Translation Layer
            </h3>
            <div class="prose prose-sm text-gray-700 max-w-none">
              <p>Because MODFLOW-USG's Upstream Weighting treats dry cells below the basin as gravity-driven seepage faces, the standard formulation does not inherently capture the capillary suction of dry soil (which causes initial infiltration rates to be much higher than the saturated hydraulic conductivity).</p>
              <p>To capture this vital physical process, BaSIM uses the <strong>Initial Infiltration Approach</strong> to map Green-Ampt suction mechanics into an Effective Hydraulic Conductivity (K<sub>eff</sub>) for the clogging layer.</p>
              
              <h4 class="text-md font-semibold mt-4 mb-2 text-gray-800">The Mathematics</h4>
              <p>The infiltration flux (q) is defined by Darcy's Law across the clogging layer (thickness L<sub>clog</sub>):</p>
              <div class="bg-gray-100 p-3 rounded text-center font-mono my-2 border border-gray-200">
                q = K<sub>eff</sub> &times; (H<sub>pond</sub> + L<sub>clog</sub>) / L<sub>clog</sub>
              </div>
              <p>We equate this to the Green-Ampt flux equation:</p>
              <div class="bg-gray-100 p-3 rounded text-center font-mono my-2 border border-gray-200">
                q<sub>GA</sub> = K<sub>clog</sub> &times; (H<sub>pond</sub> + L<sub>clog</sub> + &psi;) / L<sub>clog</sub>
              </div>
              <p>Where &psi; is the capillary suction head. By equating the two, we solve for K<sub>eff</sub>:</p>
              <div class="bg-gray-100 p-3 rounded text-center font-mono my-2 border border-gray-200">
                K<sub>eff</sub> = K<sub>clog</sub> &times; [ 1 + &psi; / (H<sub>pond</sub> + L<sub>clog</sub>) ]
              </div>
              
              <h4 class="text-md font-semibold mt-4 mb-2 text-gray-800">The Sizing Approach Explained</h4>
              <p>The Initial Infiltration Approach determines what ponding depth (H<sub>pond</sub>) the system is calibrated to:</p>
              <ul class="list-disc pl-5 space-y-2 mt-2">
                <li><strong>Conservative (Saturated)</strong>: Calibrates the flux to the Maximum Basin Depth (H<sub>pond</sub> = Max Depth). This minimises the proportional impact of the capillary suction term (&psi;), yielding a lower K<sub>eff</sub> and a larger required basin volume. Best for continuous storms or pre-saturated soil conditions.</li>
                <li><strong>Optimistic (Dry Soil)</strong>: Calibrates the flux to 10% of the Maximum Basin Depth (H<sub>pond</sub> = 0.1 &times; Max Depth). This maximises the mathematical impact of capillary suction, mimicking the rapid initial draw of a dry soil profile. This yields a higher K<sub>eff</sub> and a smaller required basin volume. Best for isolated, brief storms in well-drained soils.</li>
              </ul>
            </div>
          </section>

          <section class="mb-8">
            <h3 class="text-xl font-semibold text-blue-800 mb-3 border-b pb-2">
              5. Outlet Hydraulics (Post-Processing)
            </h3>
            <div class="prose prose-sm text-gray-700 max-w-none">
              <p>You may notice that MODFLOW-USG does not natively handle complex piped outlets, weirs, or grated structures. Instead of wrestling with rigid boundary condition packages during the simulation, BaSIM handles outlet hydraulics via a highly accurate post-processing mass balance.</p>
              
              <h4 class="text-md font-semibold mt-4 mb-2 text-gray-800">How It Works</h4>
              <ol class="list-decimal pl-5 space-y-2 mt-2">
                <li><strong>Baseline Simulation</strong>: MODFLOW-USG runs the full groundwater simulation to establish the dynamic infiltration rates based on the groundwater mounding and aquifer properties.</li>
                <li><strong>Hydraulic Routing</strong>: After the simulation completes, the engine steps through the timeseries and recalculates the basin's water mass balance at every timestep: <code>Volume = Volume + (Inflow - Infiltration - Outflow) * dt</code>.</li>
                <li><strong>Picard Iteration</strong>: Because Outflow depends on the Stage, and Stage depends on the Volume, BaSIM uses a Picard iteration scheme with relaxation at every timestep to solve for the exact equilibrium Stage and Outflow simultaneously.</li>
              </ol>

              <h4 class="text-md font-semibold mt-4 mb-2 text-gray-800">Supported Structures</h4>
              <ul class="list-disc pl-5 space-y-1 mt-2 mb-4">
                <li><strong>Piped Outlets</strong>: Automatically transitions between Inlet Control (weir/orifice flow) and Outlet Control (Manning's full-pipe flow) depending on the stage.</li>
                <li><strong>Broad Crested Weirs</strong>: Standard weir equation (Q = Cd * L * h^1.5 * sqrt(2g)).</li>
                <li><strong>Grated Inlets</strong>: Solves for the minimum of perimeter weir flow and grate-area orifice flow (as recommended by QUDM).</li>
              </ul>
            </div>
          </section>

          <section class="mb-8">
            <h3 class="text-xl font-semibold text-blue-800 mb-3 border-b pb-2">
              6. Aquifer Parameters Glossary
            </h3>
            <div class="prose prose-sm text-gray-700 max-w-none">
              <p>Understanding the fundamental groundwater parameters used in BaSIM.</p>
              
              <div class="mt-4 space-y-4">
                <div class="bg-blue-50 border border-blue-100 p-4 rounded">
                  <h4 class="font-bold text-blue-900 mb-1">Hydraulic Conductivity (K<sub>h</sub>, K<sub>v</sub>)</h4>
                  <p class="text-sm">The rate at which water can move through the soil, measured in meters per day (m/day). K<sub>h</sub> governs lateral groundwater mounding, while K<sub>v</sub> governs vertical infiltration.</p>
                </div>

                <div class="bg-blue-50 border border-blue-100 p-4 rounded">
                  <h4 class="font-bold text-blue-900 mb-1">Specific Yield (S<sub>y</sub>)</h4>
                  <p class="text-sm">The ratio of the volume of water a rock or soil will yield by gravity drainage to the volume of the rock or soil. For unconfined aquifers, S<sub>y</sub> represents the drainable porosity. For example, an S<sub>y</sub> of 0.20 means that 20% of the aquifer's volume consists of interconnected voids that can freely drain.</p>
                </div>

                <div class="bg-blue-50 border border-blue-100 p-4 rounded">
                  <h4 class="font-bold text-blue-900 mb-1">Specific Storage (S<sub>s</sub>)</h4>
                  <p class="text-sm">The volume of water that a unit volume of aquifer releases from storage under a unit decline in hydraulic head, due to the expansion of water and compression of the soil matrix. Typically a very small value (e.g., 1 &times; 10<sup>-4</sup>) that governs confined flow behavior deep below the water table.</p>
                </div>

                <div class="bg-blue-50 border border-blue-100 p-4 rounded">
                  <h4 class="font-bold text-blue-900 mb-1">Capillary Suction Head (&psi;)</h4>
                  <p class="text-sm">The negative pressure (tension) in the soil matrix caused by capillary forces in dry or partially saturated soil. It acts as a vacuum, physically pulling water into the soil faster than gravity alone. Typical values range from 0.05m for coarse sand up to &gt;0.30m for clay.</p>
                </div>
              </div>
            </div>
          </section>

        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
// Technical Reference View Component
</script>
