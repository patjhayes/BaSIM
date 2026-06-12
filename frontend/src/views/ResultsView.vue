<template>
  <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
    <div class="bg-white rounded-lg shadow p-6">
      <h2 class="text-lg font-semibold text-gray-900 mb-4">Results</h2>
      <p class="text-gray-600">After runs complete, results will render here. For now this is a placeholder with mocked content.</p>
      <div class="mt-6 grid grid-cols-1 md:grid-cols-2 gap-6">
        <div class="bg-gray-50 rounded-lg p-4">
          <div class="text-sm text-gray-500">Peak Stage (m)</div>
          <div class="text-2xl font-semibold text-gray-900">2.14</div>
        </div>
        <div class="bg-gray-50 rounded-lg p-4">
          <div class="text-sm text-gray-500">Time to Peak (h)</div>
          <div class="text-2xl font-semibold text-gray-900">3.7</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
// Future: fetch results from /api/results/{id} and plot with Chart.js
</script>
