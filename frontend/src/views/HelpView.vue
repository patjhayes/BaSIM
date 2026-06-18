<template>
  <div class="h-full bg-gray-50 flex flex-col p-6 overflow-y-auto">
    <div class="max-w-4xl mx-auto bg-white rounded-xl shadow-sm border border-gray-200 p-8">
      <h1 class="text-3xl font-bold text-gray-900 mb-2">Technical Reference</h1>
      <p class="text-gray-600 mb-8 border-b pb-4">Understanding the physics and math powering BaSIM.</p>

      <div class="space-y-10">
        
        <section>
          <h2 class="text-xl font-semibold text-blue-800 mb-3 flex items-center">
            <svg class="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z"></path></svg>
            1. The Core Engine
          </h2>
          <div class="prose prose-sm text-gray-700 max-w-none">
            <p>BaSIM is powered by <strong>MODFLOW-USG</strong> (Unstructured Grid), utilizing the advanced Unconfined Upstream Weighting (UUF) formulation. This engine rigorously solves the 3D groundwater flow equation (Darcy's Law combined with mass conservation).</p>
            <p>Traditional drainage calculators often assume a fixed infiltration rate or use simplified analytical models (like the Hantush equation). BaSIM physically routes water through a dynamically generated unstructured mesh, accounting for:</p>
            <ul class="list-disc pl-5 space-y-1">
              <li>Groundwater mounding and lateral dispersion</li>
              <li>Aquifer boundaries and initial water table elevations</li>
              <li>Transient feedback (infiltration rates decrease as the groundwater mound rises to meet the basin floor)</li>
            </ul>
          </div>
        </section>

        <section>
          <h2 class="text-xl font-semibold text-blue-800 mb-3 flex items-center">
            <svg class="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4"></path></svg>
            2. Pseudo-Lake Architecture
          </h2>
          <div class="prose prose-sm text-gray-700 max-w-none">
            <p>To accurately simulate the filling and emptying of the infiltration basin without requiring external routing packages, BaSIM employs a "Pseudo-Lake" architecture.</p>
            <p>The basin itself is represented as the top layer (Layer 0) of the groundwater model. This layer is assigned:</p>
            <ul class="list-disc pl-5 space-y-1">
              <li><strong>Specific Yield ($S_y$) = 1.0</strong>: Meaning it represents 100% void space (open water).</li>
              <li><strong>Hydraulic Conductivity ($K$) = 100 m/day</strong>: Creating instantaneous horizontal equilibration of the water level across the basin footprint.</li>
            </ul>
            <p>Surface runoff from the catchment (either ILSAX or TS1 hydrographs) is injected directly into this layer. The water then infiltrates downwards into the underlying aquifer layers governed by Darcy's Law.</p>
          </div>
        </section>

        <section>
          <h2 class="text-xl font-semibold text-blue-800 mb-3 flex items-center">
            <svg class="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path></svg>
            3. The Effective K Translation Layer
          </h2>
          <div class="prose prose-sm text-gray-700 max-w-none">
            <p>Because MODFLOW-USG's Upstream Weighting treats dry cells below the basin as gravity-driven seepage faces, the standard formulation does not inherently capture the capillary suction of dry soil (which causes initial infiltration rates to be much higher than the saturated hydraulic conductivity).</p>
            <p>To capture this vital physical process, BaSIM uses the <strong>Initial Infiltration Approach</strong> slider to map Green-Ampt suction mechanics into an Effective Hydraulic Conductivity ($K_{eff}$) for the clogging layer.</p>
            
            <h3 class="text-md font-semibold mt-4 mb-2 text-gray-800">The Mathematics</h3>
            <p>The infiltration flux ($q$) is defined by Darcy's Law across the clogging layer (thickness $L_{clog}$):</p>
            <div class="bg-gray-100 p-3 rounded text-center font-mono my-2 border border-gray-200">
              q = K_{eff} * (H_{pond} + L_{clog}) / L_{clog}
            </div>
            <p>We equate this to the Green-Ampt flux equation:</p>
            <div class="bg-gray-100 p-3 rounded text-center font-mono my-2 border border-gray-200">
              q_{GA} = K_{clog} * (H_{pond} + L_{clog} + \psi) / L_{clog}
            </div>
            <p>Where $\psi$ is the capillary suction head. By equating the two, we solve for $K_{eff}$:</p>
            <div class="bg-gray-100 p-3 rounded text-center font-mono my-2 border border-gray-200">
              K_{eff} = K_{clog} * [ 1 + \psi / (H_{pond} + L_{clog}) ]
            </div>
            
            <h3 class="text-md font-semibold mt-4 mb-2 text-gray-800">The Slider Explained</h3>
            <p>The <strong>Initial Infiltration Approach</strong> slider determines what ponding depth ($H_{pond}$) the system is calibrated to:</p>
            <ul class="list-disc pl-5 space-y-2 mt-2">
              <li><strong>Conservative (Saturated)</strong>: Calibrates the flux to the Maximum Basin Depth ($H_{pond} = Max Depth$). This minimizes the proportional impact of the capillary suction term ($\psi$), yielding a lower $K_{eff}$ and a larger required basin volume. Best for continuous storms or pre-saturated soil conditions.</li>
              <li><strong>Optimistic (Dry Soil)</strong>: Calibrates the flux to 10% of the Maximum Basin Depth ($H_{pond} = 0.1 \times Max Depth$). This maximizes the mathematical impact of capillary suction, mimicking the rapid initial draw of a dry soil profile. This yields a higher $K_{eff}$ and a smaller required basin volume. Best for isolated, brief storms in well-drained soils.</li>
            </ul>
          </div>
        </section>

      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
// Help View Component
</script>
