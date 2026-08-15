import { defineStore } from 'pinia'
import { getProfile, login as loginApi } from '../api/auth'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem('jjc_token') || '',
    user: JSON.parse(localStorage.getItem('jjc_user') || 'null'),
    profileLoaded: false,
  }),
  getters: {
    isAuthenticated: (state) => Boolean(state.token),
    hasPermission: (state) => (code) => Boolean(state.user?.permissions?.includes(code)),
    hasAnyPermission: (state) => Boolean(state.user?.permissions?.length),
  },
  actions: {
    async login(form) {
      const result = await loginApi(form)
      const data = result.data
      this.token = data.access_token
      localStorage.setItem('jjc_token', this.token)
      await this.loadProfile()
    },
    async loadProfile() {
      if (!this.token) return null
      const result = await getProfile()
      this.user = result.data
      this.profileLoaded = true
      localStorage.setItem('jjc_user', JSON.stringify(this.user))
      return this.user
    },
    logout() {
      this.token = ''
      this.user = null
      this.profileLoaded = false
      localStorage.removeItem('jjc_token')
      localStorage.removeItem('jjc_user')
    },
  },
})
