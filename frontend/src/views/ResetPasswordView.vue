<template>
  <div class="min-h-screen bg-gray-50 flex flex-col justify-center py-12 sm:px-6 lg:px-8">
    <div class="sm:mx-auto sm:w-full sm:max-w-md text-center">
      <div class="mx-auto h-12 w-12 rounded bg-blue-600 text-white flex items-center justify-center font-bold text-2xl select-none">B</div>
      <h2 class="mt-6 text-center text-3xl font-extrabold text-gray-900">Reset your password</h2>
      <p class="mt-2 text-center text-sm text-gray-600">
        Enter your new password below.
      </p>
    </div>

    <div class="mt-8 sm:mx-auto sm:w-full sm:max-w-md">
      <div class="bg-white py-8 px-4 shadow sm:rounded-lg sm:px-10">
        <form class="space-y-6" @submit.prevent="handleReset">
          <div>
            <label for="password" class="block text-sm font-medium text-gray-700">New Password</label>
            <div class="mt-1">
              <input id="password" v-model="password" name="password" type="password" required class="appearance-none block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm placeholder-gray-400 focus:outline-none focus:ring-blue-500 focus:border-blue-500 sm:text-sm" />
            </div>
          </div>

          <div v-if="errorMessage" class="rounded-md bg-red-50 p-4">
            <div class="flex">
              <div class="ml-3">
                <h3 class="text-sm font-medium text-red-800">{{ errorMessage }}</h3>
              </div>
            </div>
          </div>
          
          <div v-if="successMessage" class="rounded-md bg-green-50 p-4">
            <div class="flex">
              <div class="ml-3">
                <h3 class="text-sm font-medium text-green-800">{{ successMessage }}</h3>
              </div>
            </div>
          </div>

          <div>
            <button type="submit" :disabled="isLoading" class="w-full flex justify-center py-2 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50">
              <span v-if="isLoading">Saving...</span>
              <span v-else>Update Password</span>
            </button>
          </div>
          
          <div class="text-center mt-4">
            <router-link to="/auth" class="text-sm font-medium text-blue-600 hover:text-blue-500">
              Back to Sign in
            </router-link>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { supabase } from '../supabase'

const router = useRouter()
const password = ref('')
const isLoading = ref(false)
const errorMessage = ref('')
const successMessage = ref('')

// Check if we arrived here via a password reset link (hash contains access_token)
onMounted(() => {
  if (!window.location.hash.includes('access_token')) {
    errorMessage.value = "Invalid or expired reset link. Please try requesting a new one from the sign-in page."
  }
})

const handleReset = async () => {
  isLoading.value = true
  errorMessage.value = ''
  successMessage.value = ''
  
  try {
    const { error } = await supabase.auth.updateUser({ password: password.value })
    if (error) throw error
    
    successMessage.value = 'Password successfully updated! Redirecting...'
    
    // Redirect to home page after a brief delay
    setTimeout(() => {
      router.push('/')
    }, 2000)
    
  } catch (error: any) {
    errorMessage.value = error.message
  } finally {
    isLoading.value = false
  }
}
</script>
