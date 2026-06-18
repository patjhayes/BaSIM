<template>
  <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
    <div class="sm:flex sm:items-center">
      <div class="sm:flex-auto">
        <h1 class="text-2xl font-semibold text-gray-900">Project Billing & Token Usage</h1>
        <p class="mt-2 text-sm text-gray-700">Manage your simulation credits. 1 run = 1 credit.</p>
      </div>
      <div class="mt-4 sm:mt-0 sm:ml-16 sm:flex-none space-x-3">
        <button @click="fetchData" class="inline-flex items-center justify-center rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2">
          Refresh
        </button>
        <button @click="purchaseCredits" :disabled="!projectCodeFilter || purchasing" class="inline-flex items-center justify-center rounded-md border border-transparent bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50">
          {{ purchasing ? 'Redirecting...' : 'Buy 1000 Credits ($100)' }}
        </button>
      </div>
    </div>
    
    <!-- Filter & Balance -->
    <div class="mt-6 flex space-x-6 items-end">
      <div class="w-1/3">
        <label for="projectCodeFilter" class="block text-sm font-medium text-gray-700">Active Project Code</label>
        <div class="mt-1 flex rounded-md shadow-sm">
          <input v-model="projectCodeFilter" @change="fetchData" type="text" id="projectCodeFilter" class="block w-full rounded-md border-gray-300 focus:border-blue-500 focus:ring-blue-500 sm:text-sm" placeholder="e.g. PRJ-2026-001">
        </div>
        <p class="text-xs text-gray-500 mt-1">Enter a project code to view its balance and history.</p>
      </div>
      
      <div v-if="projectCodeFilter" class="bg-blue-50 rounded-lg border border-blue-200 px-6 py-3 flex items-center space-x-4">
        <div>
          <p class="text-xs font-semibold text-blue-800 uppercase tracking-wide">Current Balance</p>
          <p class="text-2xl font-bold text-blue-900">{{ currentBalance !== null ? currentBalance : '---' }}</p>
        </div>
      </div>
    </div>

    <!-- Admin Panel -->
    <div v-if="isAdmin" class="mt-6 bg-red-50 border border-red-200 rounded-lg p-4">
      <h3 class="text-sm font-bold text-red-800 mb-2">Admin Tools</h3>
      <div class="flex space-x-3 items-end">
        <div>
          <label class="block text-xs font-medium text-red-700">Project Code</label>
          <input v-model="adminProject" type="text" class="mt-1 block w-full rounded-md border-gray-300 sm:text-sm">
        </div>
        <div>
          <label class="block text-xs font-medium text-red-700">Amount (+/-)</label>
          <input v-model.number="adminAmount" type="number" class="mt-1 block w-full rounded-md border-gray-300 sm:text-sm">
        </div>
        <div>
          <label class="block text-xs font-medium text-red-700">Description</label>
          <input v-model="adminDesc" type="text" class="mt-1 block w-full rounded-md border-gray-300 sm:text-sm">
        </div>
        <button @click="submitAdminAdjustment" class="inline-flex items-center justify-center rounded-md border border-transparent bg-red-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-red-700">
          Adjust
        </button>
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
                  <th scope="col" class="px-3 py-3.5 text-left text-sm font-semibold text-gray-900">Description</th>
                  <th scope="col" class="px-3 py-3.5 text-right text-sm font-semibold text-gray-900">Amount</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-gray-200 bg-white">
                <tr v-if="loading">
                  <td colspan="4" class="py-4 text-center text-sm text-gray-500">Loading ledger data...</td>
                </tr>
                <tr v-else-if="ledger.length === 0">
                  <td colspan="4" class="py-4 text-center text-sm text-gray-500">No records found for this project.</td>
                </tr>
                <tr v-for="entry in ledger" :key="entry.id">
                  <td class="whitespace-nowrap py-4 pl-4 pr-3 text-sm text-gray-900 sm:pl-6">{{ new Date(entry.created_at).toLocaleString() }}</td>
                  <td class="whitespace-nowrap px-3 py-4 text-sm text-gray-500 font-mono">{{ entry.project_code }}</td>
                  <td class="whitespace-nowrap px-3 py-4 text-sm text-gray-500">{{ entry.description || entry.type }}</td>
                  <td :class="['whitespace-nowrap px-3 py-4 text-sm font-medium text-right', entry.amount > 0 ? 'text-green-600' : 'text-red-600']">
                    {{ entry.amount > 0 ? '+' : '' }}{{ entry.amount }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { supabase } from '../supabase'
import axios from 'axios'

const getApiBase = () => {
  const url = import.meta.env.VITE_API_URL;
  if (!url) return 'http://localhost:8000';
  return url.startsWith('http') ? url : `https://${url}`;
};
const API_BASE = getApiBase();

const loading = ref(false)
const purchasing = ref(false)
const ledger = ref<any[]>([])
const projectCodeFilter = ref('')
const currentBalance = ref<number | null>(null)

// Admin
const isAdmin = ref(false)
const adminProject = ref('')
const adminAmount = ref(0)
const adminDesc = ref('')

const fetchData = async () => {
  if (!projectCodeFilter.value) {
    ledger.value = []
    currentBalance.value = null
    return
  }
  
  loading.value = true
  
  // Fetch Balance from backend
  try {
    const res = await axios.get(`${API_BASE}/api/billing/balance/${projectCodeFilter.value}`)
    currentBalance.value = res.data.credit_balance
  } catch (e: any) {
    if (e.response && e.response.status === 404) {
      currentBalance.value = 0
    } else {
      console.error(e)
    }
  }

  // Fetch Ledger directly from Supabase (RLS protects this)
  const { data, error } = await supabase
    .from('transactions')
    .select('*')
    .eq('project_code', projectCodeFilter.value)
    .order('created_at', { ascending: false })
  
  if (!error) {
    ledger.value = data || []
  }
  
  loading.value = false
}

const purchaseCredits = async () => {
  if (!projectCodeFilter.value) return
  purchasing.value = true
  try {
    const res = await axios.post(`${API_BASE}/api/billing/checkout/${projectCodeFilter.value}`)
    if (res.data.payment_url) {
      window.location.href = res.data.payment_url
    }
  } catch (e: any) {
    alert("Failed to initiate checkout: " + (e.response?.data?.detail || e.message))
    purchasing.value = false
  }
}

const submitAdminAdjustment = async () => {
  if (!adminProject.value || !adminAmount.value) return
  try {
    await axios.post(`${API_BASE}/api/billing/admin/adjust_credits`, {
      project_code: adminProject.value,
      amount: adminAmount.value,
      description: adminDesc.value || 'Admin Adjustment'
    })
    alert('Adjustment successful')
    if (adminProject.value === projectCodeFilter.value) fetchData()
  } catch (e: any) {
    alert("Failed: " + (e.response?.data?.detail || e.message))
  }
}

onMounted(async () => {
  const { data: { session } } = await supabase.auth.getSession()
  if (session?.user?.email === 'Patrick@innealta.com.au') {
    isAdmin.value = true
  }
})
</script>
