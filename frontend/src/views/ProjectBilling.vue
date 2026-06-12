<template>
  <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
    <div class="sm:flex sm:items-center">
      <div class="sm:flex-auto">
        <h1 class="text-2xl font-semibold text-gray-900">Project Billing & Token Usage</h1>
        <p class="mt-2 text-sm text-gray-700">A detailed ledger of simulation runs for client disbursement.</p>
      </div>
      <div class="mt-4 sm:mt-0 sm:ml-16 sm:flex-none">
        <button @click="fetchLedger" class="inline-flex items-center justify-center rounded-md border border-transparent bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 sm:w-auto">
          Refresh Ledger
        </button>
      </div>
    </div>
    
    <!-- Filter -->
    <div class="mt-6">
      <label for="projectCodeFilter" class="block text-sm font-medium text-gray-700">Filter by Project Code</label>
      <div class="mt-1 flex rounded-md shadow-sm w-1/3">
        <input v-model="projectCodeFilter" type="text" id="projectCodeFilter" class="block w-full rounded-md border-gray-300 focus:border-blue-500 focus:ring-blue-500 sm:text-sm" placeholder="e.g. PRJ-2026-001">
      </div>
    </div>

    <!-- Table -->
    <div class="mt-8 flex flex-col">
      <div class="-my-2 -mx-4 overflow-x-auto sm:-mx-6 lg:-mx-8">
        <div class="inline-block min-w-full py-2 align-middle md:px-6 lg:px-8">
          <div class="overflow-hidden shadow ring-1 ring-black ring-opacity-5 md:rounded-lg">
            <table class="min-w-full divide-y divide-gray-300">
              <thead class="bg-gray-50">
                <tr>
                  <th scope="col" class="py-3.5 pl-4 pr-3 text-left text-sm font-semibold text-gray-900 sm:pl-6">Date</th>
                  <th scope="col" class="px-3 py-3.5 text-left text-sm font-semibold text-gray-900">Project Code</th>
                  <th scope="col" class="px-3 py-3.5 text-left text-sm font-semibold text-gray-900">User ID</th>
                  <th scope="col" class="px-3 py-3.5 text-right text-sm font-semibold text-gray-900">Tokens Used</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-gray-200 bg-white">
                <tr v-if="loading">
                  <td colspan="4" class="py-4 text-center text-sm text-gray-500">Loading ledger data...</td>
                </tr>
                <tr v-else-if="filteredLedger.length === 0">
                  <td colspan="4" class="py-4 text-center text-sm text-gray-500">No records found.</td>
                </tr>
                <tr v-for="entry in filteredLedger" :key="entry.id">
                  <td class="whitespace-nowrap py-4 pl-4 pr-3 text-sm text-gray-900 sm:pl-6">{{ new Date(entry.timestamp).toLocaleString() }}</td>
                  <td class="whitespace-nowrap px-3 py-4 text-sm text-gray-500 font-mono">{{ entry.project_code }}</td>
                  <td class="whitespace-nowrap px-3 py-4 text-sm text-gray-500 font-mono text-xs">{{ entry.user_id }}</td>
                  <td class="whitespace-nowrap px-3 py-4 text-sm text-gray-900 text-right">{{ entry.credits_used }}</td>
                </tr>
              </tbody>
              <tfoot class="bg-gray-50" v-if="filteredLedger.length > 0">
                <tr>
                  <th scope="row" colspan="3" class="hidden pl-6 pr-3 pt-4 text-right text-sm font-semibold text-gray-900 sm:table-cell sm:pl-0">Total Computed</th>
                  <td class="pl-3 pr-4 pt-4 text-right text-sm font-semibold text-gray-900 sm:pr-6">{{ totalTokens }}</td>
                </tr>
              </tfoot>
            </table>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { supabase } from '../supabase'

const loading = ref(true)
const ledger = ref<any[]>([])
const projectCodeFilter = ref('')

const filteredLedger = computed(() => {
  if (!projectCodeFilter.value) return ledger.value
  return ledger.value.filter(e => e.project_code.toLowerCase().includes(projectCodeFilter.value.toLowerCase()))
})

const totalTokens = computed(() => {
  return filteredLedger.value.reduce((acc, curr) => acc + curr.credits_used, 0)
})

const fetchLedger = async () => {
  loading.value = true
  const { data, error } = await supabase
    .from('credit_ledger')
    .select('*')
    .order('timestamp', { ascending: false })
  
  if (error) {
    console.error('Error fetching ledger:', error)
  } else {
    ledger.value = data || []
  }
  loading.value = false
}

onMounted(() => {
  fetchLedger()
})
</script>
