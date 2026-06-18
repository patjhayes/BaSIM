<template>
  <div class="h-full bg-gray-50 flex flex-col p-6 overflow-y-auto">
    <div class="max-w-4xl mx-auto bg-white rounded-xl shadow-sm border border-gray-200 p-8">
      <h1 class="text-3xl font-bold text-gray-900 mb-2">Technical Reference</h1>
      <p class="text-gray-600 mb-8 border-b pb-4">Understanding the physics and math powering BaSIM.</p>

      <div class="space-y-10">
        
        <section>
          <h2 class="text-xl font-semibold text-blue-800 mb-3 border-b pb-2">
            1. The Core Engine
          </h2>
          <div class="prose prose-sm text-gray-700 max-w-none">
            <p>BaSIM is powered by <strong>MODFLOW-USG</strong> (Unstructured Grid), utilizing the advanced Unconfined Upstream Weighting (UUF) formulation. This engine rigorously solves the 3D groundwater flow equation (Darcy's Law combined with mass conservation).</p>
            <p>Traditional drainage calculators often assume a fixed infiltration rate or use simplified analytical models (like the Hantush equation). BaSIM physically routes water through a dynamically generated unstructured mesh, accounting for:</p>
            <ul class="list-disc pl-5 space-y-1 mt-2 mb-4">
              <li>Groundwater mounding and lateral dispersion</li>
              <li>Aquifer boundaries and initial water table elevations</li>
              <li>Transient feedback (infiltration rates decrease as the groundwater mound rises to meet the basin floor)</li>
            </ul>
          </div>
        </section>

        <section>
          <h2 class="text-xl font-semibold text-blue-800 mb-3 border-b pb-2">
            2. Hydrology & Runoff Routing
          </h2>
          <div class="prose prose-sm text-gray-700 max-w-none">
            <p>BaSIM handles catchment hydrology through the proven <strong>ILSAX</strong> (Illawarra Area Simulator) routing methodology, or by accepting externally generated hydrographs (TS1 format).</p>
            
            <h3 class="text-md font-semibold mt-4 mb-2 text-gray-800">Rainfall & Temporal Patterns</h3>
            <p>When using the internal hydrology engine, BaSIM integrates directly with the Australian Rainfall and Runoff (ARR) Datahub. It automatically retrieves the <strong>Intensity-Frequency-Duration (IFD)</strong> data and the regional <strong>Temporal Patterns</strong> based on the provided coordinate location.</p>
            <p>The engine simulates the full ensemble of 10 temporal patterns for each duration to identify the critical storm event that produces the highest median peak water level in the basin.</p>

            <h3 class="text-md font-semibold mt-4 mb-2 text-gray-800">ILSAX Routing</h3>
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

        <section>
          <h2 class="text-xl font-semibold text-blue-800 mb-3 border-b pb-2">
            3. Pseudo-Lake Architecture
          </h2>
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

        <section>
          <h2 class="text-xl font-semibold text-blue-800 mb-3 border-b pb-2">
            4. The Effective K Translation Layer
          </h2>
          <div class="prose prose-sm text-gray-700 max-w-none">
            <p>Because MODFLOW-USG's Upstream Weighting treats dry cells below the basin as gravity-driven seepage faces, the standard formulation does not inherently capture the capillary suction of dry soil (which causes initial infiltration rates to be much higher than the saturated hydraulic conductivity).</p>
            <p>To capture this vital physical process, BaSIM uses the <strong>Initial Infiltration Approach</strong> to map Green-Ampt suction mechanics into an Effective Hydraulic Conductivity (K<sub>eff</sub>) for the clogging layer.</p>
            
            <h3 class="text-md font-semibold mt-4 mb-2 text-gray-800">The Mathematics</h3>
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
            
            <h3 class="text-md font-semibold mt-4 mb-2 text-gray-800">The Sizing Approach Explained</h3>
            <p>The Initial Infiltration Approach determines what ponding depth (H<sub>pond</sub>) the system is calibrated to:</p>
            <ul class="list-disc pl-5 space-y-2 mt-2">
              <li><strong>Conservative (Saturated)</strong>: Calibrates the flux to the Maximum Basin Depth (H<sub>pond</sub> = Max Depth). This minimizes the proportional impact of the capillary suction term (&psi;), yielding a lower K<sub>eff</sub> and a larger required basin volume. Best for continuous storms or pre-saturated soil conditions.</li>
              <li><strong>Optimistic (Dry Soil)</strong>: Calibrates the flux to 10% of the Maximum Basin Depth (H<sub>pond</sub> = 0.1 &times; Max Depth). This maximizes the mathematical impact of capillary suction, mimicking the rapid initial draw of a dry soil profile. This yields a higher K<sub>eff</sub> and a smaller required basin volume. Best for isolated, brief storms in well-drained soils.</li>
            </ul>
          </div>
        </section>

        <section>
          <h2 class="text-xl font-semibold text-blue-800 mb-3 border-b pb-2">
            5. Aquifer Parameters Glossary
          </h2>
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
</template>

<script setup lang="ts">
// Technical Reference View Component
</script>
