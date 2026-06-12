import { createRouter, createWebHistory } from 'vue-router'
import DesignView from './views/DesignView.vue'

const routes = [
  { path: '/', component: DesignView },
  { path: '/results/:id?', component: () => import('./views/ResultsView.vue') },
  { path: '/billing', component: () => import('./views/ProjectBilling.vue') },
  { path: '/help', component: () => import('./views/HelpView.vue') },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
