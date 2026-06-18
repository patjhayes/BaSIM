import { createRouter, createWebHistory } from 'vue-router'
import { supabase } from './supabase'
import DesignView from './views/DesignView.vue'

const routes = [
  { path: '/', component: DesignView, meta: { requiresAuth: true } },
  { path: '/results/:id?', component: () => import('./views/ResultsView.vue'), meta: { requiresAuth: true } },
  { path: '/billing', component: () => import('./views/ProjectBilling.vue'), meta: { requiresAuth: true } },
  { path: '/help', component: () => import('./views/HelpView.vue'), meta: { requiresAuth: true } },
  { path: '/calibrate', component: () => import('./views/CalibrationView.vue'), meta: { requiresAuth: true } },
  { path: '/auth', component: () => import('./views/AuthView.vue') },
  { path: '/reset-password', component: () => import('./views/ResetPasswordView.vue') },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to, from, next) => {
  const { data: { session } } = await supabase.auth.getSession()
  
  if (to.meta.requiresAuth && !session) {
    next('/auth')
  } else if (to.path === '/auth' && session) {
    next('/')
  } else {
    next()
  }
})

export default router
