<template>
  <div class="min-h-screen bg-gray-50 flex flex-col justify-center py-12 sm:px-6 lg:px-8">
    <div class="sm:mx-auto sm:w-full sm:max-w-md text-center">
      <div class="mx-auto h-12 w-12 rounded bg-blue-600 text-white flex items-center justify-center font-bold text-2xl select-none">B</div>
      <h2 class="mt-6 text-center text-3xl font-extrabold text-gray-900">Sign in to BaSIM</h2>
      <p class="mt-2 text-center text-sm text-gray-600">
        Or
        <a href="#" @click.prevent="isLogin = !isLogin" class="font-medium text-blue-600 hover:text-blue-500">
          {{ isLogin ? 'create a new account' : 'sign in to your existing account' }}
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

          <div>
            <label for="password" class="block text-sm font-medium text-gray-700">Password</label>
            <div class="mt-1">
              <input id="password" v-model="password" name="password" type="password" autocomplete="current-password" required class="appearance-none block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm placeholder-gray-400 focus:outline-none focus:ring-blue-500 focus:border-blue-500 sm:text-sm" />
            </div>
          </div>
          
          <div v-if="!isLogin">
            <p class="text-xs text-gray-500 mt-2">
              Corporate emails will automatically group you into your company's workspace. Generic emails (gmail, etc.) will create a Solo Workspace.
            </p>
          </div>

          <div v-if="errorMessage" class="rounded-md bg-red-50 p-4">
            <div class="flex">
              <div class="ml-3">
                <h3 class="text-sm font-medium text-red-800">{{ errorMessage }}</h3>
              </div>
            </div>
          </div>

          <div>
            <button type="submit" :disabled="isLoading" class="w-full flex justify-center py-2 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50">
              <span v-if="isLoading">Processing...</span>
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
const email = ref('')
const password = ref('')
const isLoading = ref(false)
const errorMessage = ref('')

const handleSubmit = async () => {
  isLoading.value = true
  errorMessage.value = ''
  
  try {
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
