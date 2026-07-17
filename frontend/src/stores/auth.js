import { defineStore } from 'pinia'
import { login as loginApi } from '../api/auth'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem('jjc_token') || '',
    user: JSON.parse(localStorage.getItem('jjc_user') || 'null'),
  }),
  getters: {
    isAuthenticated: (state) => Boolean(state.token),
  },
  actions: {
    async login(form) {
      const result = await loginApi(form)
      const data = result.data
      this.token = data.access_token
      this.user = data.user || { username: form.username || 'admin', role: '管理员' }
      localStorage.setItem('jjc_token', this.token)
      localStorage.setItem('jjc_user', JSON.stringify(this.user))
    },
    logout() {
      this.token = ''
      this.user = null
      localStorage.removeItem('jjc_token')
      localStorage.removeItem('jjc_user')
    },
  },
})
