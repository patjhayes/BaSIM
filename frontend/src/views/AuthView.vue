<template>
  <div class="min-h-screen bg-gray-50 flex flex-col justify-center py-12 sm:px-6 lg:px-8">
    <div class="sm:mx-auto sm:w-full sm:max-w-md text-center">
      <div class="mx-auto h-12 w-12 rounded bg-blue-600 text-white flex items-center justify-center font-bold text-2xl select-none">B</div>
      <h2 class="mt-6 text-center text-3xl font-extrabold text-gray-900">Sign in to your Innealta Account</h2>
      <p class="mt-2 text-center text-sm text-gray-600">
        One account for BaSIM, SoakSIM, and SubsoilSIM
      </p>
      <p class="mt-2 text-center text-sm text-gray-600">
        <a href="#" @click.prevent="isLogin = !isLogin; isForgotPassword = false" class="font-medium text-blue-600 hover:text-blue-500">
          {{ isLogin ? 'Need an account? Create one' : 'Already have an account? Sign in' }}
        </a>
      </p>
    </div>

    <div class="mt-8 sm:mx-auto sm:w-full sm:max-w-md">
      <div class="bg-white py-8 px-4 shadow sm:rounded-lg sm:px-10">
        <form class="space-y-6" @submit.prevent="handleSubmit">
          <div>
            <label for="email" class="block text-sm font-medium text-gray-700">Email address</label>
            <div class="mt-1">
              <input id="email" v-model="email" name="email" type="email" autocomplete="email" required class="appearance-none block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm placeholder-gray-400 focus:outline-none focus:ring-blue-500 focus:border-blue-500 sm:text-sm" />
            </div>
          </div>

          <div v-if="!isForgotPassword">
            <div class="flex items-center justify-between">
              <label for="password" class="block text-sm font-medium text-gray-700">Password</label>
              <div class="text-sm" v-if="isLogin">
                <a href="#" @click.prevent="isForgotPassword = true" class="font-medium text-blue-600 hover:text-blue-500">
                  Forgot your password?
                </a>
              </div>
            </div>
            <div class="mt-1">
              <input id="password" v-model="password" name="password" type="password" autocomplete="current-password" required class="appearance-none block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm placeholder-gray-400 focus:outline-none focus:ring-blue-500 focus:border-blue-500 sm:text-sm" />
            </div>
          </div>
          
          <div v-if="!isLogin && !isForgotPassword">
            <p class="text-xs text-gray-500 mt-2">
              Corporate emails will automatically group you into your company's workspace. Generic emails (gmail, etc.) will create a Solo Workspace.
            </p>
            <p class="text-xs text-gray-500 mt-4 text-center">
              By signing up, you agree to our 
              <router-link to="/eula" target="_blank" class="text-blue-600 hover:underline">End User License Agreement (EULA)</router-link>.
            </p>
          </div>

          <div v-if="isForgotPassword" class="text-center">
            <a href="#" @click.prevent="isForgotPassword = false" class="text-sm font-medium text-blue-600 hover:text-blue-500">
              Back to sign in
            </a>
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
              <span v-if="isLoading">Processing...</span>
              <span v-else-if="isForgotPassword">Send reset link</span>
              <span v-else>{{ isLogin ? 'Sign in' : 'Create account' }}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { supabase } from '../supabase'

const router = useRouter()
const isLogin = ref(true)
const isForgotPassword = ref(false)
const email = ref('')
const password = ref('')
const isLoading = ref(false)
const errorMessage = ref('')
const successMessage = ref('')

const handleSubmit = async () => {
  isLoading.value = true
  errorMessage.value = ''
  successMessage.value = ''
  
  try {
    if (isForgotPassword.value) {
      const { error } = await supabase.auth.resetPasswordForEmail(email.value, {
        redirectTo: window.location.origin + '/reset-password',
      })
      if (error) throw error
      successMessage.value = 'Check your email for the password reset link.'
      isLoading.value = false
      return
    }

    if (isLogin.value) {
      const { error } = await supabase.auth.signInWithPassword({
        email: email.value,
        password: password.value,
      })
      if (error) throw error
    } else {
      const { error } = await supabase.auth.signUp({
        email: email.value,
        password: password.value,
      })
      if (error) throw error
      
      // If email confirmation is required, Supabase returns a user but session is null
      const { data: { session } } = await supabase.auth.getSession()
      if (!session) {
        errorMessage.value = 'Check your email for the confirmation link.'
        isLoading.value = false
        return
      }
    }
    
    // Redirect to home
    router.push('/')
  } catch (error: any) {
    errorMessage.value = error.message
  } finally {
    isLoading.value = false
  }
}
</script>
