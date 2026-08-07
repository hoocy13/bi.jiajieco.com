import { defineStore } from 'pinia'
import { getTheme, THEME_OPTIONS, THEME_STORAGE_KEY, THEMES } from '../utils/theme'

function savedTheme() {
  const value = localStorage.getItem(THEME_STORAGE_KEY)
  return THEMES[value] ? value : 'indigo'
}

export const useThemeStore = defineStore('theme', {
  state: () => ({ name: savedTheme() }),
  getters: {
    current: (state) => getTheme(state.name),
    options: () => THEME_OPTIONS,
  },
  actions: {
    apply(name = this.name) {
      this.name = THEMES[name] ? name : 'indigo'
      document.documentElement.dataset.theme = this.name
      localStorage.setItem(THEME_STORAGE_KEY, this.name)
    },
    initialize() { this.apply(this.name) },
  },
})
