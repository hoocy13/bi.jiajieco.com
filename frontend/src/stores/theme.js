import { defineStore } from 'pinia'
import { APPEARANCE_OPTIONS, APPEARANCE_STORAGE_KEY, getTheme, THEME_OPTIONS, THEME_STORAGE_KEY, THEMES } from '../utils/theme'

function savedTheme() {
  const value = localStorage.getItem(THEME_STORAGE_KEY)
  return THEMES[value] ? value : 'indigo'
}

function savedAppearance() {
  const value = localStorage.getItem(APPEARANCE_STORAGE_KEY)
  return ['light', 'dark', 'system'].includes(value) ? value : 'system'
}

export const useThemeStore = defineStore('theme', {
  state: () => ({ name: savedTheme(), appearance: savedAppearance(), systemDark: false, mediaQuery: null }),
  getters: {
    current: (state) => getTheme(state.name),
    options: () => THEME_OPTIONS,
    appearanceOptions: () => APPEARANCE_OPTIONS,
    resolvedAppearance: (state) => state.appearance === 'system' ? (state.systemDark ? 'dark' : 'light') : state.appearance,
    isDark() { return this.resolvedAppearance === 'dark' },
  },
  actions: {
    apply(name = this.name) {
      this.name = THEMES[name] ? name : 'indigo'
      document.documentElement.dataset.theme = this.name
      localStorage.setItem(THEME_STORAGE_KEY, this.name)
    },
    applyAppearance(name = this.appearance) {
      this.appearance = ['light', 'dark', 'system'].includes(name) ? name : 'system'
      const resolved = this.appearance === 'system' ? (this.systemDark ? 'dark' : 'light') : this.appearance
      document.documentElement.dataset.appearance = resolved
      document.documentElement.dataset.appearancePreference = this.appearance
      document.documentElement.classList.toggle('dark', resolved === 'dark')
      document.documentElement.style.colorScheme = resolved
      localStorage.setItem(APPEARANCE_STORAGE_KEY, this.appearance)
    },
    initialize() {
      this.apply(this.name)
      if (!this.mediaQuery) {
        this.mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
        this.systemDark = this.mediaQuery.matches
        this.mediaQuery.addEventListener('change', (event) => {
          this.systemDark = event.matches
          if (this.appearance === 'system') this.applyAppearance('system')
        })
      }
      this.applyAppearance(this.appearance)
    },
  },
})
