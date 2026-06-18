<template>
  <div id="app">
    <div class="min-h-screen bg-gray-50">
      <header class="bg-white shadow-sm border-b">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div class="flex justify-between items-center h-16">
            <div class="flex items-center">
              <div class="h-8 w-8 rounded bg-blue-600 text-white flex items-center justify-center font-bold select-none">B</div>
              <h1 class="ml-3 text-xl font-semibold text-gray-900">BaSIM</h1>
            </div>
            <nav class="flex space-x-4">
              <router-link to="/" class="text-gray-700 hover:text-blue-600 px-3 py-2 rounded-md text-sm font-medium">Design</router-link>
              <router-link to="/calibrate" class="text-gray-700 hover:text-blue-600 px-3 py-2 rounded-md text-sm font-medium">Calibration</router-link>
              <router-link to="/billing" class="text-gray-700 hover:text-blue-600 px-3 py-2 rounded-md text-sm font-medium">Project Billing</router-link>
              <router-link to="/help" class="text-gray-700 hover:text-blue-600 px-3 py-2 rounded-md text-sm font-medium">Technical Reference</router-link>
            </nav>
          </div>
        </div>
      </header>
      <router-view />
    </div>
  </div>
</template>

<script setup lang="ts">
</script>

