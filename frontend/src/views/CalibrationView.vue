<template>
  <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
    <!-- Top Bar with User Info -->
    <div class="flex justify-end space-x-6 text-xs text-gray-400 mb-4">
      <div class="flex items-center">
        <span class="mr-2">Company ID:</span>
        <input v-model="config.company_id" type="text" class="bg-transparent border-b border-gray-200 p-0 focus:ring-0 focus:border-gray-400 w-64 text-gray-400 text-xs" placeholder="e.g. 123e4567-e89b-12d3-a456-426614174000">
      </div>
      <div class="flex items-center">
        <span class="mr-2">User ID:</span>
        <input v-model="config.user_id" type="text" class="bg-transparent border-b border-gray-200 p-0 focus:ring-0 focus:border-gray-400 w-64 text-gray-400 text-xs" placeholder="e.g. 123e4567-e89b-12d3-a456-426614174000">
      </div>
    </div>
    
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-8">
      <!-- Left Panel - Configuration -->
      <div class="lg:col-span-1 space-y-6">
        
        <!-- Project Details -->
        <div class="bg-white rounded-lg shadow p-6 border-l-4 border-blue-500">
          <h2 class="text-lg font-semibold text-gray-900 mb-4">Project Details</h2>
          <div class="space-y-3">
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">Project Code <span class="text-red-500">*</span></label>
              <input v-model="config.project_code" type="text" class="w-full px-3 py-2 border border-gray-300 rounded-md text-sm" placeholder="e.g. PRJ-2026-001">
            </div>
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">Project Name</label>
              <input v-model="config.project_name" type="text" class="w-full px-3 py-2 border border-gray-300 rounded-md text-sm" placeholder="e.g. Oakwood Subdivision">
            </div>
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">Scenario Name</label>
              <input v-model="config.scenario_name" type="text" class="w-full px-3 py-2 border border-gray-300 rounded-md text-sm" placeholder="e.g. Pre-Development Base Case">
            </div>
          </div>
        </div>

        <!-- Calibration Data Source -->
        <div class="bg-white rounded-lg shadow p-6 border-l-4 border-teal-500">
          <h2 class="text-lg font-semibold text-gray-900 mb-4">Calibration Data</h2>
          
          <div class="space-y-4">
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-2">1. Upload Modeled Inflow (TS1 format)</label>
              <input
                type="file"
                @change="handleTS1Upload"
                accept=".ts1"
                class="block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-md file:border-0 file:text-sm file:font-semibold file:bg-teal-50 file:text-teal-700 hover:file:bg-teal-100"
              >
              <div v-if="config.ts1_files.length > 0" class="mt-2 text-sm text-green-600 font-medium">
                ✓ TS1 Hydrograph loaded
              </div>
            </div>

            <div>
              <label class="block text-sm font-medium text-gray-700 mb-2">2. Upload Observed Water Levels (CSV: Time, Stage)</label>
              <input
                type="file"
                @change="handleObservedUpload"
                accept=".csv"
                class="block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-md file:border-0 file:text-sm file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100"
              >
              <div v-if="observedDataLoaded" class="mt-2 text-sm text-green-600 font-medium">
                ✓ Observed timeseries loaded
              </div>
            </div>
          </div>
        </div>

        <!-- Basin Configuration -->
        <div class="bg-white rounded-lg shadow p-6">
          <h2 class="text-lg font-semibold text-gray-900 mb-4">Basin Geometry & Aquifer</h2>
          <div class="space-y-3">
             <div class="mb-3">
               <label class="text-xs text-gray-500 font-bold block mb-1">Geometry Type</label>
               <select v-model="config.basin_geometry.geometry_mode" class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm">
                 <option value="rectangle">Standard Rectangle</option>
                 <option value="shapefile">Custom Shapefile (.zip)</option>
               </select>
             </div>

             <div v-if="config.basin_geometry.geometry_mode === 'rectangle'" class="grid grid-cols-2 gap-2">
               <div>
                 <label class="text-xs text-gray-500">Length (m)</label>
                 <input v-model.number="config.basin_geometry.length_floor" type="number" class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" min="1" step="0.5">
               </div>
               <div>
                 <label class="text-xs text-gray-500">Width (m)</label>
                 <input v-model.number="config.basin_geometry.width_floor" type="number" class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" min="1" step="0.5">
               </div>
             </div>

             <div v-else class="bg-gray-50 p-3 rounded-md border border-gray-200">
               <label class="text-xs text-gray-700 font-semibold mb-1 block">Upload Shapefile (.zip)</label>
               <p class="text-xs text-gray-500 mb-2">Must contain .shp, .shx, and .dbf files representing the basin floor polygon.</p>
               <input
                 type="file"
                 @change="handleShapefileUpload"
                 accept=".zip"
                 class="block w-full text-xs text-gray-500 file:mr-2 file:py-1 file:px-2 file:rounded file:border-0 file:text-xs file:font-semibold file:bg-indigo-50 file:text-indigo-700 hover:file:bg-indigo-100"
               >
               <div v-if="config.basin_geometry.custom_polygon_coords?.length > 0" class="mt-2 text-xs text-green-600 font-medium">
                 ✓ Polygon loaded ({{ config.basin_geometry.custom_polygon_coords.length }} points)
               </div>
             </div>
             
             <div class="grid grid-cols-2 gap-2">
               <div>
                <label class="text-xs text-gray-500">Floor Elev (m AHD)</label>
                <input v-model.number="config.basin_geometry.floor_elev" type="number" class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" step="0.1">
               </div>
               <div>
                <label class="text-xs text-gray-500">Max Depth (m)</label>
                <input v-model.number="config.basin_geometry.max_depth" type="number" class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" min="0.5" max="10" step="0.1">
               </div>
             </div>
             
             <div>
               <label class="text-xs text-gray-500">Side Slope (1 in X, 0 for vertical)</label>
               <input v-model.number="config.basin_geometry.side_slope_1_in" type="number" class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" min="0" step="0.5">
             </div>
            
            <div class="mt-4">
              <label class="text-xs text-gray-500 block mb-1">Aquifer Material</label>
              <select v-model="config.aquifer.soil_type" class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm">
                <option value="Custom">Custom</option>
                <option value="Gravel">Gravel</option>
                <option value="Sand">Sand</option>
                <option value="Loamy Sand">Loamy Sand</option>
                <option value="Sandy Loam">Sandy Loam</option>
                <option value="Silt Loam">Silt Loam</option>
                <option value="Clay">Clay</option>
              </select>
            </div>
            
            <div class="grid grid-cols-2 gap-2 mt-2">
              <div>
                <label class="text-xs text-gray-500">Aquifer Kh (m/day)</label>
                <input v-model.number="config.aquifer.k_horizontal_mpd" type="number" class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" min="0.01" step="0.1">
              </div>
              <div>
                <label class="text-xs text-gray-500">Initial Head (m AHD)</label>
                <input v-model.number="config.aquifer.initial_head" type="number" class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" step="0.1">
              </div>
            </div>
            
            <div class="mt-2">
              <button @click="advancedAquiferOpen = !advancedAquiferOpen" class="text-xs text-blue-600 hover:text-blue-800 font-semibold flex items-center focus:outline-none">
                <svg class="w-4 h-4 mr-1 transition-transform" :class="{'rotate-90': advancedAquiferOpen}" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path></svg>
                Advanced Aquifer Parameters
              </button>
              
              <div v-if="advancedAquiferOpen" class="mt-3 grid grid-cols-2 gap-2 bg-gray-50 p-3 rounded border border-gray-200">
                <div>
                  <label class="text-xs text-gray-500">Vertical Kv (m/day)</label>
                  <input v-model.number="config.aquifer.k_vertical_mpd" type="number" class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm" min="0.01" step="0.1">
                </div>
                <div>
                  <label class="text-xs text-gray-500">Specific Yield (Sy)</label>
                  <input v-model.number="config.aquifer.sy" type="number" class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm" min="0.01" max="1.0" step="0.01">
                </div>
                <div>
                  <label class="text-xs text-gray-500">Specific Storage (Ss)</label>
                  <input v-model.number="config.aquifer.ss" type="number" class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm" min="0.00001" step="0.0001">
                </div>
                <div>
                  <label class="text-xs text-gray-500">Aq. Bottom (m AHD)</label>
                  <input v-model.number="config.aquifer.aquifer_bottom" type="number" class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm" step="1.0">
                </div>
              </div>
            </div>
            
            <div class="pt-4 border-t mt-4 border-gray-200">
              <h3 class="text-sm font-semibold text-gray-800 mb-2">Clogging Layer (Infiltration)</h3>
              <div class="grid grid-cols-2 gap-2">
                <div>
                  <label class="text-xs text-gray-500">Bed K (m/day)</label>
                  <input v-model.number="config.infiltration.bed_k_mpd" type="number" class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" min="0.001" step="0.1">
                </div>
                <div>
                  <label class="text-xs text-gray-500">Thickness (m)</label>
                  <input v-model.number="config.infiltration.bed_thickness_m" type="number" class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" min="0.01" step="0.1">
                </div>
              </div>
              <div class="mt-2">
                <label class="text-xs text-gray-500 block mb-1">Infiltration Mode</label>
                <select v-model="config.infiltration.mode" class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm">
                  <option value="vertical">Vertical Only (Bottom)</option>
                  <option value="full">Full (Bottom + Sidewalls)</option>
                </select>
              </div>
              <div class="mt-4 pt-3 border-t border-gray-200">
                <label class="text-xs font-semibold text-gray-700 block mb-2">Initial Infiltration Approach</label>
                <div class="flex justify-between text-xs text-gray-500 px-1 mb-1">
                  <span title="Minimizes the effect of initial soil suction. Best for continuous storm events or pre-saturated soil conditions. Results in a larger basin volume.">Conservative (Saturated)</span>
                  <span title="Accounts heavily for initial dry-soil capillary suction. Best for isolated, brief storm events in well-drained soils. Results in a smaller basin volume.">Optimistic (Dry Soil)</span>
                </div>
                <input 
                  type="range" 
                  v-model.number="config.infiltration.h_threshold_pct" 
                  min="0.1" 
                  max="1.0" 
                  step="0.05"
                  class="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"
                  style="direction: rtl;"
                >
                <div class="text-center text-xs text-gray-400 mt-1">Design Head Threshold: {{ Math.round(config.infiltration.h_threshold_pct * 100) }}%</div>
              </div>
            </div>
            
            <!-- Stage Storage Curve -->
            <div class="pt-4 border-t mt-4 border-gray-200">
              <h3 class="text-sm font-semibold text-gray-800 mb-2">Stage-Storage Curve</h3>
              <div class="h-48 w-full">
                <Line ref="chartStageStorage" :data="stageStorageChartData" :options="stageStorageChartOptions" />
              </div>
            </div>
            
            <!-- Basin Geometry Map -->
            <div class="pt-4 border-t mt-4 border-gray-200">
              <h3 class="text-sm font-semibold text-gray-800 mb-2">Basin Footprint Map</h3>
              <div class="h-48 w-full bg-white border border-gray-200 rounded-md p-2">
                <Scatter ref="chartGeometry" :data="geometryChartData" :options="geometryChartOptions" />
              </div>
            </div>
          </div>
        </div>

        <!-- Outlet Configuration -->
        <div class="bg-white rounded-lg shadow p-6 border-l-4 border-indigo-500">
          <div class="flex justify-between items-center mb-4">
            <h2 class="text-lg font-semibold text-gray-900">Hydraulic Outlets</h2>
            <button @click="addOutlet" class="text-xs bg-indigo-100 text-indigo-700 px-2 py-1 rounded hover:bg-indigo-200 font-semibold">+ Add Outlet</button>
          </div>
          
          <div v-if="config.outlets.length === 0" class="text-sm text-gray-500 italic text-center py-4">
            No outlets configured. The basin will retain all water.
          </div>

          <div v-for="(outlet, index) in config.outlets" :key="index" class="mb-4 p-3 border border-gray-200 rounded-md bg-gray-50 relative">
            <button @click="removeOutlet(index)" class="absolute top-2 right-2 text-gray-400 hover:text-red-500">
              ✕
            </button>
            <div class="mb-2 pr-6">
              <label class="text-xs text-gray-500 font-semibold">Type</label>
              <select v-model="outlet.type" class="w-full px-2 py-1 border border-gray-300 rounded-md text-sm mt-1">
                <option value="pipe">Pipe / Culvert</option>
                <option value="weir">Broad Crested Weir</option>
                <option value="grate">Grated Inlet</option>
              </select>
            </div>
            
            <div v-if="outlet.type === 'pipe'" class="grid grid-cols-2 gap-2 mt-2">
              <div>
                <label class="text-xs text-gray-500">Diameter (m)</label>
                <input v-model.number="outlet.diameter_m" type="number" class="w-full px-2 py-1 border border-gray-300 rounded-md text-sm" step="0.1">
              </div>
              <div>
                <label class="text-xs text-gray-500">Invert (m AHD)</label>
                <input v-model.number="outlet.invert_mAHD" type="number" class="w-full px-2 py-1 border border-gray-300 rounded-md text-sm" step="0.1">
              </div>
              <div>
                <label class="text-xs text-gray-500">Length (m)</label>
                <input v-model.number="outlet.length_m" type="number" class="w-full px-2 py-1 border border-gray-300 rounded-md text-sm" step="1">
              </div>
              <div>
                <label class="text-xs text-gray-500">Grade (m/m)</label>
                <input v-model.number="outlet.grade" type="number" class="w-full px-2 py-1 border border-gray-300 rounded-md text-sm" step="0.01">
              </div>
            </div>

            <div v-if="outlet.type === 'weir'" class="grid grid-cols-2 gap-2 mt-2">
              <div>
                <label class="text-xs text-gray-500">Crest Width (m)</label>
                <input v-model.number="outlet.crest_length_m" type="number" class="w-full px-2 py-1 border border-gray-300 rounded-md text-sm" step="0.1">
              </div>
              <div>
                <label class="text-xs text-gray-500">Crest Elev (m AHD)</label>
                <input v-model.number="outlet.crest_mAHD" type="number" class="w-full px-2 py-1 border border-gray-300 rounded-md text-sm" step="0.1">
              </div>
            </div>

            <div v-if="outlet.type === 'grate'" class="grid grid-cols-2 gap-2 mt-2">
              <div>
                <label class="text-xs text-gray-500">Grate Area (m²)</label>
                <input v-model.number="outlet.grate_area_m2" type="number" class="w-full px-2 py-1 border border-gray-300 rounded-md text-sm" step="0.1">
              </div>
              <div>
                <label class="text-xs text-gray-500">Crest Elev (m AHD)</label>
                <input v-model.number="outlet.crest_mAHD" type="number" class="w-full px-2 py-1 border border-gray-300 rounded-md text-sm" step="0.1">
              </div>
              <div class="col-span-2">
                <label class="text-xs text-gray-500">Perimeter (m)</label>
                <input v-model.number="outlet.perimeter_m" type="number" class="w-full px-2 py-1 border border-gray-300 rounded-md text-sm" step="0.1">
              </div>
            </div>
            
            <div class="mt-2 flex items-center">
              <input type="checkbox" v-model="outlet.enabled" class="mr-2 h-3 w-3 text-indigo-600 focus:ring-indigo-500 border-gray-300 rounded">
              <span class="text-xs text-gray-600 font-medium">Enabled</span>
            </div>
          </div>
        </div>

        <!-- Run Button -->
        <button @click="submitJob" :disabled="isRunning || !isValid" class="w-full bg-blue-600 text-white py-3 px-4 rounded-md hover:bg-blue-700 transition-colors disabled:bg-gray-400 disabled:cursor-not-allowed font-medium shadow-md">
          <span v-if="!isRunning">🚀 Run Simulation</span>
          <span v-else>⏳ Running...</span>
        </button>
        <p v-if="config.inflow_source === 'ts1' && config.ts1_files.length === 0" class="text-red-500 text-sm mt-2">Please upload at least one TS1 file.</p>
        <p v-if="queueError" class="text-red-600 text-sm mt-2 font-semibold">{{ queueError }}</p>
      </div>

      <!-- Right Panel - Visualization & Progress -->
      <div class="lg:col-span-2 space-y-6">
        <!-- Tab Navigation for Right Panel -->
        <div class="flex justify-between items-center border-b border-gray-200">
          <div class="flex space-x-1">
            <button 
              @click="activeRightTab = 'simulation'"
              :class="['px-4 py-2 text-sm font-medium border-b-2 transition-colors', activeRightTab === 'simulation' ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300']"
            >
              Simulation Tracking
            </button>
            <button 
              @click="activeRightTab = 'observed_data'"
              :class="['px-4 py-2 text-sm font-medium border-b-2 transition-colors', activeRightTab === 'observed_data' ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300']"
            >
              Observed Data Inspector
            </button>
          </div>
          <button @click="downloadReport" :disabled="isRunning || !lastResults" :class="['px-3 py-1.5 text-sm rounded font-medium shadow flex items-center transition-colors mb-1', (!isRunning && lastResults) ? 'bg-green-600 text-white hover:bg-green-700' : 'bg-gray-200 text-gray-400 cursor-not-allowed']">
            <svg class="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path></svg>
            Download Report & CSV
          </button>
        </div>

        <div v-if="activeRightTab === 'simulation'">
          <div v-if="isRunning || lastResults" class="bg-white rounded-lg shadow p-6">
          <div class="flex justify-between items-center mb-4">
            <h3 class="text-lg font-semibold text-gray-900">{{ isRunning ? 'Job Status Tracker' : 'Simulation Complete' }}</h3>
            
            <div class="flex space-x-3 items-center">
            <!-- Duration Tabs for Ensemble -->
            <div v-if="!isRunning && isILSAXEnsemble" class="flex space-x-1 bg-gray-100 p-1 rounded-md">
              <button 
                v-for="(data, dur) in lastResults.durations" 
                :key="dur"
                @click="activeDuration = String(dur)"
                :class="['px-3 py-1 text-xs rounded-md font-medium transition-colors', activeDuration === String(dur) ? 'bg-white shadow text-blue-700' : 'text-gray-600 hover:text-gray-900']"
              >
                {{ dur }} min
              </button>
            </div>
            </div>
          </div>

          <div v-if="isRunning" class="space-y-4">
            <div>
              <div class="flex justify-between text-sm text-gray-600 mb-1">
                <span class="font-mono text-xs">Job ID: {{ currentJobId }}</span>
                <span class="font-bold text-blue-600">{{ jobStatus.toUpperCase() }}</span>
              </div>
              <div class="w-full bg-gray-200 rounded-full h-3">
                <div class="bg-blue-600 h-3 rounded-full transition-all duration-1000" :style="{ width: progressWidth }"></div>
              </div>
              <div class="text-xs text-gray-500 mt-1 italic">{{ progressMessage }}</div>
            </div>

            <!-- Detailed Tracker Grid -->
            <div v-if="subtasks.length > 0" class="mt-4">
              <div class="text-sm font-semibold text-gray-700 mb-2">Simulation Subtasks ({{ subtasksCompleted }} / {{ subtasks.length }})</div>
              <div class="flex flex-wrap gap-2 max-h-60 overflow-y-auto p-2 bg-gray-50 border border-gray-200 rounded-md">
                <div v-for="(task, i) in subtasks" :key="i"
                     :class="[
                       'text-xs px-2 py-1 rounded border whitespace-nowrap',
                       task.status === 'queued' ? 'bg-white border-gray-300 text-gray-500' :
                       task.status === 'running' ? 'bg-blue-50 border-blue-400 text-blue-700 animate-pulse' :
                       task.status === 'completed' ? 'bg-green-50 border-green-500 text-green-700' :
                       'bg-red-50 border-red-500 text-red-700'
                     ]">
                  <span v-if="task.status === 'running'" class="inline-block mr-1">🔄</span>
                  <span v-else-if="task.status === 'completed'" class="inline-block mr-1">✅</span>
                  <span v-else-if="task.status === 'failed'" class="inline-block mr-1">❌</span>
                  {{ task.name }}
                </div>
              </div>
            </div>
          </div>

          <div v-if="!isRunning && lastResults" class="space-y-6 mt-4">
            
            <!-- TS1 Calibration Results -->
            <div v-if="lastResults.type === 'ts1_batch' && lastResults.calibration">
              <div class="mb-4">
                <div class="bg-teal-50 border border-teal-200 rounded p-4 relative text-center">
                  <div class="text-xs text-teal-600 font-bold uppercase mb-1">Nash-Sutcliffe Efficiency (NSE)</div>
                  <div class="text-4xl font-black" :class="{'text-green-600': lastResults.calibration.nse > 0.7, 'text-orange-500': lastResults.calibration.nse > 0.4 && lastResults.calibration.nse <= 0.7, 'text-red-600': lastResults.calibration.nse <= 0.4}">
                    {{ lastResults.calibration.nse.toFixed(3) }}
                  </div>
                  <div class="text-xs text-gray-500 mt-2">1.0 is perfect match. &gt;0.7 is good.</div>
                </div>
              </div>

              <!-- Calibration Graph -->
              <div class="mt-8 border border-gray-200 rounded-lg p-4 bg-white shadow-sm">
                <div class="flex justify-between items-center mb-4">
                  <h3 class="text-md font-semibold text-gray-800">Calibration Hydrograph</h3>
                </div>
                
                <div class="h-80">
                  <Line ref="chartCalibration" :data="calibrationChartData" :options="chartOptions" />
                </div>
              </div>
            </div>
            
            <div v-else-if="lastResults.type === 'ts1_batch'" class="text-orange-600">
              Calibration processing failed: {{ lastResults.calibration_error || 'Unknown error' }}
            </div>
          </div>
          
          <!-- Empty State -->
          <div v-if="!isRunning && !lastResults" class="bg-white rounded-lg shadow p-12 text-center border-2 border-dashed border-gray-300">
            <svg class="mx-auto h-12 w-12 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 002-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
            </svg>
            <h3 class="mt-2 text-sm font-medium text-gray-900">No Simulation Results</h3>
            <p class="mt-1 text-sm text-gray-500">Run a simulation from the left panel to see tracking and results here.</p>
          </div>
        </div>
        </div>

        <!-- Observed Data Inspector Tab -->
        <div v-if="activeRightTab === 'observed_data'" class="space-y-6">
          <div class="bg-white rounded-lg shadow p-6">
            <h3 class="text-lg font-semibold text-gray-900 mb-4">Calibration Data Configuration</h3>
            <div class="space-y-4">
              <div>
                <label class="block text-sm font-medium text-gray-700 mb-1">Observed Stage File (CSV/TS1)</label>
                <input type="file" @change="handleObservedUpload" class="block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-sm file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100" />
                <p v-if="observedDataLoaded" class="text-green-600 text-xs mt-1">✓ Observed data loaded.</p>
              </div>
              <div class="pt-4 border-t border-gray-200">
                <h4 class="text-sm font-semibold text-gray-800 mb-2">Instructions</h4>
                <ul class="text-xs text-gray-600 space-y-1 list-disc pl-4">
                  <li>Ensure observed data matches the simulation timesteps.</li>
                  <li>Files should contain two columns: Time (Days), Stage (m).</li>
                  <li>Calibration metrics will update automatically after run.</li>
                </ul>
              </div>
            </div>
          </div>
        </div>

        <!-- Climate Data Inspector Tab (Only visible if ILSAX) -->
        <div v-if="activeRightTab === 'climate_data' && climateData" class="space-y-6">
          <!-- IFD Depths -->
          <div class="bg-white rounded-lg shadow overflow-hidden">
            <div class="px-6 py-4 border-b border-gray-200 bg-gray-50">
              <h3 class="text-lg font-semibold text-gray-900">BoM IFD Design Rainfall Depths</h3>
            </div>
            <div class="overflow-x-auto">
              <table class="min-w-full divide-y divide-gray-200 text-sm">
                <thead class="bg-gray-50">
                  <tr>
                    <th scope="col" class="px-6 py-3 text-left font-medium text-gray-500 uppercase tracking-wider">AEP / EY</th>
                    <th v-for="dur in availableDurations" :key="dur" scope="col" class="px-6 py-3 text-left font-medium text-gray-500 uppercase tracking-wider">{{ formatDuration(dur) }}</th>
                  </tr>
                </thead>
                <tbody class="bg-white divide-y divide-gray-200">
                  <tr v-for="row in groupedIfd" :key="row.aep">
                    <td class="px-6 py-4 whitespace-nowrap font-medium text-gray-900">{{ row.aep === '1EY' ? '1 EY' : (row.aep.endsWith('%') ? row.aep : row.aep + '%') }}</td>
                    <td v-for="dur in availableDurations" :key="dur" class="px-6 py-4 whitespace-nowrap text-gray-500">
                      {{ row.durations[dur] ? row.durations[dur].toFixed(1) : '-' }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- Climate Change Factors -->
          <div v-if="climateData.ccf && Object.keys(climateData.ccf).length > 0" class="bg-white rounded-lg shadow overflow-hidden">
            <div class="px-6 py-4 border-b border-gray-200 bg-gray-50 flex justify-between items-center">
              <h3 class="text-lg font-semibold text-gray-900">ARR Datahub Climate Change Factors</h3>
              <span v-if="climateScenario === 'Historic'" class="text-xs text-orange-600 bg-orange-100 px-2 py-1 rounded">Historic scenario selected (Factors = 1.0)</span>
            </div>
            <div class="p-6 overflow-x-auto">
              <table class="min-w-full divide-y divide-gray-200 text-sm border">
                <thead class="bg-gray-50">
                  <tr>
                    <th scope="col" class="px-4 py-2 text-left font-medium text-gray-500 uppercase tracking-wider">SSP / Year</th>
                    <th v-for="dur in availableDurations" :key="'ccf-th-'+dur" scope="col" class="px-4 py-2 text-left font-medium text-gray-500 uppercase tracking-wider">{{ formatDuration(dur) }}</th>
                  </tr>
                </thead>
                <tbody class="bg-white divide-y divide-gray-200">
                  <template v-for="ssp in Object.keys(climateData.ccf)" :key="ssp">
                    <tr v-for="year in Object.keys(climateData.ccf[ssp] || {})" :key="ssp+'-'+year" :class="{'bg-blue-50': climateScenario === ssp && climateYear === year}">
                      <td class="px-4 py-2 whitespace-nowrap font-medium text-gray-900">{{ ssp }} ({{ year }})</td>
                      <td v-for="dur in availableDurations" :key="'ccf-td-'+dur" class="px-4 py-2 whitespace-nowrap text-gray-500">
                        {{ climateData.ccf[ssp][year][dur] ? climateData.ccf[ssp][year][dur].toFixed(3) : '-' }}
                      </td>
                    </tr>
                  </template>
                </tbody>
              </table>
            </div>
          </div>
        </div>

      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, shallowRef, computed, onMounted, onUnmounted, watch } from 'vue'
import { supabase } from '../supabase'
import axios from 'axios'
import 'leaflet/dist/leaflet.css'
import * as L from 'leaflet'

const getApiBase = () => {
  const url = import.meta.env.VITE_API_URL;
  if (!url) return 'http://localhost:8000';
  return url.startsWith('http') ? url : `https://${url}`;
};

const getWsBase = () => {
  const url = import.meta.env.VITE_API_URL;
  if (!url) return 'ws://localhost:8000';
  return url.startsWith('http') ? url.replace(/^http/, 'ws') : `wss://${url}`;
};

const API_BASE = getApiBase();
const WS_BASE = getWsBase();

import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler,
  ScatterController
} from 'chart.js'
import { Line, Scatter } from 'vue-chartjs'

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler,
  ScatterController
)

const chartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  interaction: {
    mode: 'index',
    intersect: false,
  },
  elements: {
    point: {
      radius: 0
    }
  },
  scales: {
    x: {
      type: 'linear',
      title: { display: true, text: 'Time (Days)' }
    }
  }
}

const durationChartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  interaction: {
    mode: 'index',
    intersect: false,
  },
  scales: {
    x: {
      type: 'linear',
      title: { display: true, text: 'Storm Duration (Minutes)' }
    },
    y: {
      title: { display: true, text: 'Median Peak Stage (m AHD)' }
    }
  }
}

const stageStorageChartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  interaction: {
    mode: 'index',
    intersect: false,
  },
  scales: {
    x: {
      type: 'linear',
      title: { display: true, text: 'Volume (m³)' }
    },
    y: {
      title: { display: true, text: 'Stage (m AHD)' }
    }
  }
}

const geometryChartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: { display: false }
  },
  scales: {
    x: {
      type: 'linear',
      title: { display: true, text: 'X (m)' },
      grid: { display: true }
    },
    y: {
      type: 'linear',
      title: { display: true, text: 'Y (m)' },
      grid: { display: true }
    }
  }
}

const soilPresets = {
  Gravel: { k_h: 100.0, k_v: 100.0, sy: 0.25, ss: 1e-4 },
  Sand: { k_h: 20.0, k_v: 20.0, sy: 0.20, ss: 1e-4 },
  'Loamy Sand': { k_h: 5.0, k_v: 5.0, sy: 0.15, ss: 1e-4 },
  'Sandy Loam': { k_h: 1.0, k_v: 1.0, sy: 0.10, ss: 1e-4 },
  'Silt Loam': { k_h: 0.2, k_v: 0.2, sy: 0.08, ss: 1e-4 },
  Clay: { k_h: 0.01, k_v: 0.01, sy: 0.02, ss: 1e-4 }
}

const advancedAquiferOpen = ref(false)

const activeRightTab = ref('simulation')

const config = ref({
  company_id: '',
  user_id: '',
  project_code: '',
  project_name: '',
  scenario_name: '',
  inflow_source: 'ts1', // fixed to ts1 for calibration
  ts1_files: [],
  observed_data_file: '', // newly added for calibration
  basin_geometry: {
    geometry_mode: 'rectangle', // 'rectangle' or 'shapefile'
    custom_polygon_coords: [],
    length_floor: 20.0,
    width_floor: 20.0,
    max_depth: 2.0,
    side_slope_1_in: 3.0,
    floor_elev: 5.0,
  },
  aquifer: {
    soil_type: 'Custom',
    k_horizontal_mpd: 10.0,
    k_vertical_mpd: 10.0,
    sy: 0.2,
    ss: 1e-4,
    initial_head: 1.0,
    aquifer_bottom: -20.0,
  },
    infiltration: {
      mode: 'vertical',
      bed_thickness_m: 0.5,
      bed_k_mpd: 5.0,
      side_k_separate: false,
      side_k_mpd: 5.0,
      h_threshold_pct: 1.0
    },
  outlets: [],
})

const stageStorageChartData = computed(() => {
  const geom = config.value.basin_geometry
  const L = geom.length_floor || 0
  const W = geom.width_floor || 0
  const z = geom.side_slope_1_in || 0
  const max_depth = geom.max_depth || 0
  
  const data = []
  const steps = 20
  
  if (geom.geometry_mode === 'shapefile' && geom.custom_polygon_coords && geom.custom_polygon_coords.length > 2) {
    // Calculate area of custom polygon
    let area = 0
    const pts = geom.custom_polygon_coords
    for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
      area += (pts[j][0] + pts[i][0]) * (pts[j][1] - pts[i][1])
    }
    area = Math.abs(area / 2.0)
    
    for (let i = 0; i <= steps; i++) {
      const h = (max_depth * i) / steps
      // Approximate as vertical walls for storage curve visualization
      const volume = area * h
      data.push({ x: volume, y: h + (geom.floor_elev || 0) })
    }
  } else {
    for (let i = 0; i <= steps; i++) {
      const h = (max_depth * i) / steps
      // V(h) = L*W*h + z*(L+W)*h^2 + (4/3)*z^2*h^3
      const volume = L * W * h + z * (L + W) * h * h + (4.0 / 3.0) * z * z * h * h * h
      data.push({ x: volume, y: h + (geom.floor_elev || 0) })
    }
  }
  
  return {
    datasets: [{
      label: 'Stage vs Storage',
      data: data,
      borderColor: 'rgb(139, 92, 246)',
      backgroundColor: 'rgba(139, 92, 246, 0.1)',
      borderWidth: 2,
      pointRadius: 0,
      fill: true,
      tension: 0.2
    }]
  }
})

const geometryChartData = computed(() => {
  const geom = config.value.basin_geometry
  let data = []
  
  if (geom.geometry_mode === 'shapefile' && geom.custom_polygon_coords && geom.custom_polygon_coords.length > 0) {
    data = geom.custom_polygon_coords.map(pt => ({ x: pt[0], y: pt[1] }))
  } else {
    // Rectangle
    const L = geom.length_floor || 20
    const W = geom.width_floor || 20
    data = [
      { x: 0, y: 0 },
      { x: L, y: 0 },
      { x: L, y: W },
      { x: 0, y: W },
      { x: 0, y: 0 } // close loop
    ]
  }

  return {
    datasets: [{
      label: 'Basin Footprint',
      data: data,
      borderColor: 'rgb(59, 130, 246)',
      backgroundColor: 'rgba(59, 130, 246, 0.2)',
      borderWidth: 2,
      pointRadius: 3,
      showLine: true,
      fill: true,
    }]
  }
})

// Climate state
const climateLocation = ref({ lat: -31.95, lon: 115.86 }) 
const isFetchingClimate = ref(false)
const climateData = shallowRef(null)

const availableAEPs = ref(['1%', '2%', '5%', '10%', '20%', '50%', '63.2%'])
const availableDurations = ref([10, 15, 20, 30, 45, 60, 90, 120, 180, 270, 360, 540, 720, 1080, 1440, 2880, 4320])

const selectedAEP = ref('1%')
const climateScenario = ref('Historic')
const climateYear = ref('2050')
const selectedDurations = ref([60])

let map = null
let marker = null

onMounted(() => {
  map = L.map('leaflet-map').setView([climateLocation.value.lat, climateLocation.value.lon], 10)
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '© OpenStreetMap'
  }).addTo(map)
  
  const icon = L.icon({
    iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
    shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
    iconAnchor: [12, 41], popupAnchor: [1, -34],
  })
  
  marker = L.marker([climateLocation.value.lat, climateLocation.value.lon], { icon }).addTo(map)
  
  map.on('click', (e) => {
    climateLocation.value.lat = parseFloat(e.latlng.lat.toFixed(5))
    climateLocation.value.lon = parseFloat(e.latlng.lng.toFixed(5))
    marker.setLatLng(e.latlng)
  })
})

const fetchClimateData = async () => {
  isFetchingClimate.value = true
  try {
    const resp = await axios.post(`${API_BASE}/api/fetch-climate`, {
      lat: climateLocation.value.lat,
      lon: climateLocation.value.lon
    })
    climateData.value = resp.data
    isFetchingClimate.value = false
    if (config.value.inflow_source === 'ilsax') {
      activeRightTab.value = 'climate_data'
    }
  } catch (err) {
    alert('Failed to fetch climate data: ' + err.message)
  } finally {
    isFetchingClimate.value = false
  }
}

// In ARR 2019, temporal patterns are grouped into 3 bins:
// Rare (<= 3.2%), Intermediate (<= 14.4%), Frequent (> 14.4%)
const getAepBin = (aep) => {
  if (aep <= 3.2) return 'rare';
  if (aep <= 14.4) return 'intermediate';
  return 'frequent';
};

const formatDuration = (mins) => {
  if (mins < 60) return `${mins} min`;
  const hrs = mins / 60;
  return `${hrs} hour${hrs !== 1 ? 's' : ''}`;
}

const generateBomCsv = () => {
  if (!climateData.value || !climateData.value.ifd) return '';
  const aeps = groupedIfd.value.map(r => r.aep);
  let csv = 'Duration,' + aeps.map(a => a === '1EY' ? '1 EY' : (a.endsWith('%') ? a : a + '%')).join(',') + '\n';
  for (const dur of availableDurations.value) {
    const row = [`${dur} min`];
    for (const group of groupedIfd.value) {
      row.push(group.durations[dur] ? group.durations[dur].toFixed(1) : '');
    }
    csv += row.join(',') + '\n';
  }
  return csv;
};

const generateArrTxt = () => {
  if (!climateData.value || !climateData.value.arr_raw_txt) return '';
  return climateData.value.arr_raw_txt;
};

const groupedIfd = computed(() => {
  if (!climateData.value || !climateData.value.ifd) return []
  
  const groups = {}
  for (const item of climateData.value.ifd) {
    if (!groups[item.aep]) {
      groups[item.aep] = { aep: item.aep, durations: {} }
    }
    groups[item.aep].durations[item.duration_minutes] = item.depth_mm
  }
  
  // Sort by AEP probability (ascending rarity)
  const getProb = (aepStr) => {
    if (aepStr.endsWith('EY')) return parseFloat(aepStr) * 100 // Approximation for sorting
    return parseFloat(aepStr)
  }
  
  return Object.values(groups).sort((a, b) => getProb(b.aep) - getProb(a.aep))
})

const displayedTemporalPatterns = computed(() => {
  if (!climateData.value || !climateData.value.temporal_patterns) return {}
  const targetBin = getAepBin(parseFloat(selectedAEP.value))
  
  const filtered = climateData.value.temporal_patterns.filter(p => getAepBin(parseFloat(p.aep_tier)) === targetBin)
  
  // Group by duration
  const grouped = {}
  for (const p of filtered) {
    if (!grouped[p.duration_minutes]) grouped[p.duration_minutes] = []
    grouped[p.duration_minutes].push(p)
  }
  
  const result = {}
  for (const dur in grouped) {
    const list = grouped[dur]
    list.sort((a, b) => {
      const rankA = a.pattern_rank || a.rank || 0;
      const rankB = b.pattern_rank || b.rank || 0;
      if (rankA !== rankB) return rankA - rankB;
      return (a.metadata?.difference_from_target || 0) - (b.metadata?.difference_from_target || 0);
    })
    result[dur] = list.slice(0, 10)
  }
  return result
})

// Build array of ensemble rainfall configurations
const prepareEnsemblePayload = () => {
  if (!climateData.value) throw new Error('Please fetch climate data first.')
  if (selectedDurations.value.length === 0) throw new Error('Please select at least one duration.')
  
  const ensemble = []
    for (const dur of selectedDurations.value) {
      // Find depth for AEP and Duration
      const ifd = climateData.value.ifd.find(i => i.aep === selectedAEP.value && i.duration_minutes === dur)
      if (!ifd) continue
      
      // Look up dynamic climate factor for this duration and SSP
      let multiplier = 1.0;
      if (climateScenario.value !== 'Historic') {
        const ccfTable = climateData.value.ccf;
        if (!ccfTable) {
          throw new Error("Climate change factors missing from ARR payload.");
        }
        if (ccfTable[climateScenario.value] && ccfTable[climateScenario.value][climateYear.value]) {
          const factor = ccfTable[climateScenario.value][climateYear.value][String(dur)];
          if (factor) {
            multiplier = factor;
          } else {
            console.warn(`No specific climate factor found for ${dur}m, applying 1.0`);
          }
        }
      }
      
      // Apply climate factor
      const totalDepth = ifd.depth_mm * multiplier
      
      const targetBin = getAepBin(parseFloat(selectedAEP.value));

    // Find temporal patterns for this duration AND matching AEP bin
    let patterns = climateData.value.temporal_patterns.filter(p => 
      p.duration_minutes === dur && getAepBin(parseFloat(p.aep_tier)) === targetBin
    );
    if (patterns.length === 0) continue
    
    // Sort to maintain deterministic order based on rank and differences
    patterns.sort((a, b) => {
      const rankA = a.pattern_rank || a.rank || 0;
      const rankB = b.pattern_rank || b.rank || 0;
      if (rankA !== rankB) return rankA - rankB;
      return (a.metadata?.difference_from_target || 0) - (b.metadata?.difference_from_target || 0);
    });
    
    // Ensure exactly 10 patterns per duration
    patterns = patterns.slice(0, 10);
    
    let rankCounter = 1;
    for (const pattern of patterns) {
      const fractions = pattern.cumulative_fractions
      const depths = []
      let prev = 0
      for (const f of fractions) {
        depths.push((f - prev) * totalDepth)
        prev = f
      }
      
      ensemble.push({
        run_name: `AEP ${selectedAEP.value}, ${dur}m, TP${rankCounter}`,
        duration_minutes: dur,
        pattern_rank: rankCounter,
        timestep_minutes: dur / fractions.length,
        depths_mm: depths
      })
      rankCounter++;
    }
  }
  
  if (ensemble.length === 0) throw new Error('Could not build any ensemble runs (missing temporal patterns).')
  config.value.ensemble_rainfalls = ensemble
}

const addOutlet = () => {
  config.value.outlets.push({
    enabled: true, type: 'pipe', diameter_m: 0.5, length_m: 10.0, invert_mAHD: 5.5, grade: 0.01,
  })
}

const removeOutlet = (index) => {
  config.value.outlets.splice(index, 1)
}

const observedDataLoaded = ref(false)

const handleShapefileUpload = async (event) => {
  const files = Array.from(event.target.files)
  if (files.length === 0) return
  
  const file = files[0]
  if (runLocally.value) {
    const formData = new FormData()
    formData.append('file', file)
    try {
      const r = await axios.post(`${API_BASE}/api/upload-shapefile`, formData)
      config.value.basin_geometry.custom_polygon_coords = r.data.points
    } catch (err) {
      console.error('Failed local shapefile upload', err)
      alert("Failed to process shapefile: " + (err.response?.data?.detail || err.message))
    }
  } else {
    alert("Shapefile upload is currently only supported in Run Locally mode.")
  }
}

watch(() => config.value.aquifer.soil_type, (newVal) => {
  if (newVal && soilPresets[newVal]) {
    const preset = soilPresets[newVal]
    config.value.aquifer.k_horizontal_mpd = preset.k_h
    config.value.aquifer.k_vertical_mpd = preset.k_v
    config.value.aquifer.sy = preset.sy
    config.value.aquifer.ss = preset.ss
  }
})

const handleTS1Upload = async (event) => {
  const files = Array.from(event.target.files)
  if (files.length === 0) return
  
  config.value.ts1_files = []
  
  const file = files[0] // only allow 1 for calibration
  const text = await file.text()
  config.value.ts1_files.push({ name: file.name, content: text })
}

const handleObservedUpload = async (event) => {
  const files = Array.from(event.target.files)
  if (files.length === 0) return
  
  const file = files[0]
  const text = await file.text()
  config.value.observed_data_file = { name: file.name, content: text }
  observedDataLoaded.value = true
}

const runLocally = ref(true)
const isRunning = ref(false)
const jobStatus = ref('queued')
const currentJobId = ref('')
const progressMessage = ref('')
const subtasks = ref([])
const subtasksCompleted = ref(0)
const lastResults = ref(null)
const queueError = ref('')
let subscription = null

const activeDuration = ref('')

const isILSAXEnsemble = computed(() => lastResults.value && lastResults.value.type === 'ilsax_ensemble')
const activeDurationData = computed(() => isILSAXEnsemble.value ? lastResults.value.durations[activeDuration.value] : null)

const isValid = computed(() => {
  if (!runLocally.value) {
    if (!config.value.project_code || !config.value.company_id || !config.value.user_id) return false
  }
  if (config.value.inflow_source === 'ts1' && config.value.ts1_files.length === 0) return false
  return true
})

const progressWidth = computed(() => {
  if (jobStatus.value === 'completed') return '100%'
  if (jobStatus.value === 'queued') return '5%'
  if (subtasks.value.length > 0) {
    const pct = Math.floor((subtasksCompleted.value / subtasks.value.length) * 100);
    return Math.max(5, Math.min(95, pct)) + '%'
  }
  return jobStatus.value === 'running' ? '50%' : '0%'
})

const chartOverall = ref(null)
const chartStage = ref(null)
const chartFlow = ref(null)
const chartStageStorage = ref(null)

const downloadReport = () => {
  const imgOverall = chartOverall.value?.chart?.toBase64Image() || ''
  const imgStage = chartStage.value?.chart?.toBase64Image() || ''
  const imgFlow = chartFlow.value?.chart?.toBase64Image() || ''
  const imgStageStorage = chartStageStorage.value?.chart?.toBase64Image() || ''

  let csv = 'Time (Days),Stage (m),Inflow (m3/s),Infiltration (m3/s),Outlet Discharge (m3/s)\n'
  if (activeDurationData.value) {
    const median = activeDurationData.value.median_run.timeseries
    for(let i=0; i<median.time_days.length; i++) {
      const inf = median.infiltration_m3s?.[i] || 0
      const out = median.outlet_discharge_m3s?.[i] || 0
      csv += `${median.time_days[i]},${median.stage_m[i]},${median.inflow_m3s[i]},${inf},${out}\n`
    }
  }

  // Download BOM CSV
  const bomCsv = generateBomCsv();
  if (bomCsv) {
    const blob = new Blob([bomCsv], { type: 'text/csv' })
    const link = document.createElement('a')
    link.href = URL.createObjectURL(blob)
    link.download = 'BOM_IFD_Data.csv'
    link.click()
  }

  // Download ARR TXT
  const arrTxt = generateArrTxt();
  if (arrTxt) {
    const blob = new Blob([arrTxt], { type: 'text/plain' })
    const link = document.createElement('a')
    link.href = URL.createObjectURL(blob)
    link.download = 'ARR_Datahub.txt'
    link.click()
  }

  let html = `
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>BaSIM Calibration Report</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; padding: 2rem; max-width: 1000px; margin: 0 auto; color: #333; }
    h1 { color: #1e3a8a; border-bottom: 2px solid #e5e7eb; padding-bottom: 0.5rem; }
    h2 { color: #2563eb; margin-top: 2rem; }
    table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
    th, td { border: 1px solid #e5e7eb; padding: 0.75rem; text-align: left; }
    th { background-color: #f9fafb; width: 40%; }
    img { max-width: 100%; height: auto; margin-top: 1rem; border: 1px solid #e5e7eb; border-radius: 4px; padding: 4px; }
  </style>
</head>
<body>
  <h1>BaSIM Calibration Report</h1>
  <p><strong>Generated:</strong> ${new Date().toLocaleString()}</p>
  
  <h2>Project Details</h2>
  <table>
    <tr><th>Company ID</th><td>${config.value.company_id || 'N/A'}</td></tr>
    <tr><th>User ID</th><td>${config.value.user_id || 'N/A'}</td></tr>
    <tr><th>Project Code</th><td>${config.value.project_code || 'N/A'}</td></tr>
    <tr><th>Project Name</th><td>${config.value.project_name || 'N/A'}</td></tr>
    <tr><th>Scenario Name</th><td>${config.value.scenario_name || 'N/A'}</td></tr>
  </table>

  <h2>Inflow Source Details (TS1 Calibration)</h2>
  <p>Externally Supplied Hydrographs (.ts1 files).</p>
  <ul>
    ${config.value.ts1_files.map(f => `<li>${typeof f === 'string' ? f.split(/[\\/]/).pop() : f.name}</li>`).join('')}
  </ul>

  <h2>Observed Data Reference</h2>
  <p>${config.value.observed_data_file ? (typeof config.value.observed_data_file === 'string' ? config.value.observed_data_file.split(/[\\/]/).pop() : config.value.observed_data_file.name) : 'None Provided'}</p>

  <h2>Basin Geometry & Aquifer</h2>
  <table>
    <tr><th>Length (m)</th><td>${config.value.basin_geometry.length_floor}</td></tr>
    <tr><th>Width (m)</th><td>${config.value.basin_geometry.width_floor}</td></tr>
    <tr><th>Side Slope (1 in X)</th><td>${config.value.basin_geometry.side_slope_1_in}</td></tr>
    <tr><th>Max Depth (m)</th><td>${config.value.basin_geometry.max_depth}</td></tr>
    <tr><th>Floor Elev (m AHD)</th><td>${config.value.basin_geometry.floor_elev}</td></tr>
    <tr><th>Aquifer K (m/day)</th><td>${config.value.aquifer.k_horizontal_mpd}</td></tr>
    <tr><th>Initial Head (m AHD)</th><td>${config.value.aquifer.initial_head}</td></tr>
  </table>

  ${imgStageStorage ? `<h3>Stage-Storage Curve</h3><img src="${imgStageStorage}" style="max-height: 400px; object-fit: contain;" />` : ''}

  <h2>Calibration Results</h2>
  <table>
    <tr><th>Median Peak Stage</th><td>${lastResults.value?.median_peak_stage?.toFixed(3) || 'N/A'} m AHD</td></tr>
    <tr><th>Max Peak Stage</th><td>${lastResults.value?.max_peak_stage?.toFixed(3) || 'N/A'} m AHD</td></tr>
  </table>
  
  ${imgStage ? `<h3>Calibration Stage Hydrograph vs Observed</h3><img src="${imgStage}" />` : ''}
  ${imgFlow ? `<h3>Modelled Flow Hydrograph</h3><img src="${imgFlow}" />` : ''}

</body>
</html>
  `

  const blobHtml = new Blob([html], { type: 'text/html' })
  const urlHtml = URL.createObjectURL(blobHtml)
  const aHtml = document.createElement('a')
  aHtml.href = urlHtml
  aHtml.download = 'BaSIM_Engineering_Report.html'
  aHtml.click()
  
  const blobCsv = new Blob([csv], { type: 'text/csv' })
  const urlCsv = URL.createObjectURL(blobCsv)
  const aCsv = document.createElement('a')
  aCsv.href = urlCsv
  aCsv.download = 'BaSIM_Raw_Results.csv'
  setTimeout(() => aCsv.click(), 500)
}

const submitJob = async () => {
  queueError.value = ''
  isRunning.value = true
  jobStatus.value = 'running'
  progressMessage.value = 'Starting...'
  lastResults.value = null
  subtasks.value = []
  subtasksCompleted.value = 0
  
  if (config.value.inflow_source === 'ilsax') {
    try {
      prepareEnsemblePayload()
      subtasks.value = config.value.ensemble_rainfalls.map(r => ({
        name: r.run_name,
        status: 'queued'
      }))
    } catch (err) {
      queueError.value = err.message
      isRunning.value = false
      return
    }
  } else if (config.value.inflow_source === 'ts1' && config.value.ts1_files) {
    subtasks.value = config.value.ts1_files.map(f => ({
      name: typeof f === 'string' ? f.split(/[\\/]/).pop().split('.')[0] : f.name.split('.')[0],
      status: 'queued'
    }))
  }
  
  if (runLocally.value) {
    try {
      const resp = await axios.post(`${API_BASE}/api/simulate`, config.value)
      currentJobId.value = resp.data.simulation_id
      
      const ws = new WebSocket(`${WS_BASE}/ws/${currentJobId.value}`)
      ws.onmessage = (e) => {
        const data = JSON.parse(e.data)
        if (data.type === 'progress') {
          jobStatus.value = 'running'
          progressMessage.value = data.message
        } else if (data.type === 'subtask_started') {
          const t = subtasks.value.find(s => s.name === data.run_name)
          if (t) t.status = 'running'
        } else if (data.type === 'subtask_completed') {
          const t = subtasks.value.find(s => s.name === data.run_name)
          if (t) t.status = data.ok ? 'completed' : 'failed'
          subtasksCompleted.value++
          progressMessage.value = `Completed ${subtasksCompleted.value} / ${subtasks.value.length}`
        } else if (data.type === 'complete') {
          isRunning.value = false
          jobStatus.value = 'completed'
          lastResults.value = data.results
          if (data.results.type === 'ilsax_ensemble') {
            activeDuration.value = String(data.results.critical_duration)
          }
          ws.close()
        } else if (data.type === 'error') {
          isRunning.value = false
          queueError.value = 'Job failed: ' + data.message
          ws.close()
        }
      }
      
      ws.onerror = (e) => {
        if (isRunning.value) {
          isRunning.value = false
          queueError.value = 'Server connection error.'
        }
      }
      
      ws.onclose = (e) => {
        if (!queueError.value) {
          queueError.value = 'Server disconnected unexpectedly.'
        }
        isRunning.value = false
      }
    } catch (err) {
      isRunning.value = false
      queueError.value = 'Failed to submit local job: ' + err.message
    }
  } else {
    // Cloud queuing logic here
    isRunning.value = false
    queueError.value = 'Cloud ensemble not implemented in this demo'
  }
}

// Chart mappings
const chartCalibration = ref(null)

const calibrationChartData = computed(() => {
  if (!lastResults.value || !lastResults.value.calibration) return { datasets: [] }
  const cal = lastResults.value.calibration
  
  const datasets = [
    {
      label: 'Observed Stage (m)',
      data: cal.observed_time.map((t, i) => ({ x: t, y: cal.observed_stage[i] })),
      borderColor: 'rgb(59, 130, 246)', // Blue
      backgroundColor: 'rgba(59, 130, 246, 0.2)',
      borderWidth: 2,
      fill: false,
      pointRadius: 0
    },
    {
      label: 'Modeled Stage (m)',
      data: cal.observed_time.map((t, i) => ({ x: t, y: cal.modeled_interpolated[i] })),
      borderColor: 'rgb(239, 68, 68)', // Red
      backgroundColor: 'rgba(239, 68, 68, 0.2)',
      borderWidth: 2,
      fill: false,
      pointRadius: 0
    }
  ]
  return { datasets }
})

const overallDurationChartData = computed(() => {
  if (!lastResults.value || !lastResults.value.durations) return { datasets: [] }
  const data = []
  
  const sortedDurs = Object.keys(lastResults.value.durations)
    .map(Number)
    .sort((a, b) => a - b)
    
  for (const dur of sortedDurs) {
    const stage = lastResults.value.durations[dur].median_peak_stage
    data.push({ x: dur, y: stage })
  }

  return {
    datasets: [{
      label: 'Median Peak Stage',
      data: data,
      borderColor: 'rgb(16, 185, 129)',
      backgroundColor: 'rgba(16, 185, 129, 0.1)',
      borderWidth: 2,
      pointRadius: 4,
      pointBackgroundColor: 'rgb(16, 185, 129)',
      fill: true,
      tension: 0.3
    }]
  }
})

const ensembleStageChartData = computed(() => {
  if (!activeDurationData.value) return { datasets: [] }
  const d = activeDurationData.value
  
  const datasets = []
  
  // Grey lines for all except median and max
  d.all_runs.forEach((r, idx) => {
    if (r !== d.median_run && r !== d.max_run) {
      datasets.push({
        label: `TP${r.run_info.pattern_rank}`,
        data: r.timeseries.time_days.map((t, i) => ({ x: t, y: r.timeseries.stage_m[i] })),
        borderColor: 'rgba(156, 163, 175, 0.5)',
        borderWidth: 1,
        fill: false,
        pointRadius: 0
      })
    }
  })
  
  // Median
  datasets.push({
    label: `Median (TP${d.median_run.run_info.pattern_rank})`,
    data: d.median_run.timeseries.time_days.map((t, i) => ({ x: t, y: d.median_run.timeseries.stage_m[i] })),
    borderColor: 'rgb(37, 99, 235)', // bold blue
    borderWidth: 3,
    fill: false,
    pointRadius: 0
  })
  
  // Max
  datasets.push({
    label: `Max (TP${d.max_run.run_info.pattern_rank})`,
    data: d.max_run.timeseries.time_days.map((t, i) => ({ x: t, y: d.max_run.timeseries.stage_m[i] })),
    borderColor: 'rgb(220, 38, 38)', // bold red
    borderWidth: 3,
    fill: false,
    pointRadius: 0
  })

  return { datasets }
})

const ensembleFlowChartData = computed(() => {
  if (!activeDurationData.value) return { datasets: [] }
  const median = activeDurationData.value.median_run.timeseries
  
  const datasets = [
    {
      label: 'Median Inflow (m³/s)',
      data: median.time_days.map((t, i) => ({ x: t, y: median.inflow_m3s[i] || 0 })),
      borderColor: 'rgb(255, 159, 64)',
      backgroundColor: 'rgba(255, 159, 64, 0.2)',
      fill: false,
    },
    {
      label: 'Median Infiltration (m³/s)',
      data: median.time_days.map((t, i) => ({ x: t, y: median.infiltration_m3s?.[i] || 0 })),
      borderColor: 'rgb(75, 192, 192)',
      backgroundColor: 'rgba(75, 192, 192, 0.2)',
      fill: false,
    }
  ]
  
  if (median.outlet_discharge_m3s) {
    datasets.push({
      label: 'Median Outlet Discharge (m³/s)',
      data: median.time_days.map((t, i) => ({ x: t, y: median.outlet_discharge_m3s[i] || 0 })),
      borderColor: 'rgb(153, 102, 255)',
      fill: false,
    })
  }

  return { datasets }
})

onUnmounted(() => {
  if (subscription) subscription.unsubscribe()
})
</script>
