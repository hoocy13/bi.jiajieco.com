import { defineStore } from 'pinia'
import { SIMPLE_THEME_STORAGE_KEY, APPEARANCE_OPTIONS, APPEARANCE_STORAGE_KEY, getTheme, STYLE_OPTIONS, STYLE_STORAGE_KEY, THEME_OPTIONS, THEME_STORAGE_KEY, THEMES } from '../utils/theme'

function savedTheme(style = localStorage.getItem(STYLE_STORAGE_KEY)) {
  const value = localStorage.getItem(style === 'classic' ? THEME_STORAGE_KEY : SIMPLE_THEME_STORAGE_KEY)
  return THEMES[value] ? value : style === 'classic' ? 'indigo' : 'green'
}

function savedAppearance() {
  const value = localStorage.getItem(APPEARANCE_STORAGE_KEY)
  return ['light', 'dark', 'system'].includes(value) ? value : 'system'
}

export const useThemeStore = defineStore('theme', {
  state: () => ({ name: savedTheme(), appearance: savedAppearance(), interfaceStyle: STYLE_OPTIONS.some(option => option.name === localStorage.getItem(STYLE_STORAGE_KEY)) ? localStorage.getItem(STYLE_STORAGE_KEY) : 'glass', systemDark: false, mediaQuery: null }),
  getters: {
    current: (state) => getTheme(state.name),
    options: () => THEME_OPTIONS,
    appearanceOptions: () => APPEARANCE_OPTIONS,
    styleOptions: () => STYLE_OPTIONS,
    currentStyle: (state) => STYLE_OPTIONS.find(option => option.name === state.interfaceStyle) || STYLE_OPTIONS[0],
    resolvedAppearance: (state) => state.appearance === 'system' ? (state.systemDark ? 'dark' : 'light') : state.appearance,
    isDark() { return this.resolvedAppearance === 'dark' },
  },
  actions: {
    applyStyle(name = this.interfaceStyle) {
      this.interfaceStyle = STYLE_OPTIONS.some(option => option.name === name) ? name : 'glass'
      document.documentElement.dataset.interfaceStyle = this.interfaceStyle
      localStorage.setItem(STYLE_STORAGE_KEY, this.interfaceStyle)
      this.apply(savedTheme(this.interfaceStyle))
    },
    apply(name = this.name) {
      this.name = THEMES[name] ? name : 'indigo'
      document.documentElement.dataset.theme = this.name
      localStorage.setItem(this.interfaceStyle === 'classic' ? THEME_STORAGE_KEY : SIMPLE_THEME_STORAGE_KEY, this.name)
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
      this.applyStyle()
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
