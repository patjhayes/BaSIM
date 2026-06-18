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
            <nav class="flex space-x-4 items-center">
              <router-link to="/" class="text-gray-700 hover:text-blue-600 px-3 py-2 rounded-md text-sm font-medium">Design</router-link>
              <router-link to="/calibrate" class="text-gray-700 hover:text-blue-600 px-3 py-2 rounded-md text-sm font-medium">Calibration</router-link>
              <router-link to="/billing" class="text-gray-700 hover:text-blue-600 px-3 py-2 rounded-md text-sm font-medium">Project Billing</router-link>
              <router-link to="/help" class="text-gray-700 hover:text-blue-600 px-3 py-2 rounded-md text-sm font-medium">Technical Reference</router-link>
              
              <div v-if="userEmail" class="border-l pl-4 ml-2 flex items-center space-x-3">
                <span class="text-xs text-gray-500">{{ userEmail }}</span>
                <button @click="handleSignOut" class="text-xs text-red-600 hover:text-red-800 font-medium border border-red-200 px-2 py-1 rounded bg-red-50">Sign Out</button>
              </div>
            </nav>
          </div>
        </div>
      </header>
      <router-view v-slot="{ Component }">
        <keep-alive>
          <component :is="Component" />
        </keep-alive>
      </router-view>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { supabase } from './supabase'

const router = useRouter()
const userEmail = ref('')

onMounted(() => {
  supabase.auth.getSession().then(({ data: { session } }) => {
    userEmail.value = session?.user?.email || ''
  })

  supabase.auth.onAuthStateChange((_event, session) => {
    userEmail.value = session?.user?.email || ''
  })
})

const handleSignOut = async () => {
  await supabase.auth.signOut()
  router.push('/auth')
}
</script>

