export const THEME_STORAGE_KEY = 'jjc_theme'
export const APPEARANCE_STORAGE_KEY = 'jjc_appearance'
export const SIMPLE_THEME_STORAGE_KEY = 'jjc_simple_theme'
export const STYLE_STORAGE_KEY = 'jjc_interface_style'
export const STYLE_OPTIONS = [
  { name: 'classic', label: '经典版', icon: 'Grid' },
  { name: 'glass', label: '简约版', icon: 'MagicStick' },
]
export const APPLE_THEME = { name: 'apple', label: '雾白 · 石墨', primary: '#39393d', strong: '#1d1d1f', soft: '#ebebed', softStrong: '#d6d6da', secondary: '#a0a0a6', pale: '#d3d3d7' }

export const THEMES = {
  mono: { name: 'mono', label: '黑白灰极简', primary: '#45454b', strong: '#252529', soft: '#eeeef0', softStrong: '#d6d6da', secondary: '#8b8b93', pale: '#c6c6cc' },
  indigo: { name: 'indigo', label: '默认靛蓝', primary: '#5e6ad2', strong: '#4f5bc4', soft: '#eef0ff', softStrong: '#d8dbfb', secondary: '#8b93e8', pale: '#cdd1ff' },
  rose: { name: 'rose', label: '品牌玫红', primary: '#e61d4f', strong: '#c8103f', soft: '#fff0f4', softStrong: '#ffe2ea', secondary: '#f07a96', pale: '#fecdd3' },
  green: { name: 'green', label: '库存绿色', primary: '#4f7f2d', strong: '#315e1b', soft: '#f0f5ec', softStrong: '#dce8d3', secondary: '#9fbd55', pale: '#c7d6a4' },
}

export const THEME_OPTIONS = Object.values(THEMES)
export const APPEARANCE_OPTIONS = [
  { name: 'light', label: '浅色外观', icon: 'Sunny' },
  { name: 'dark', label: '深色外观', icon: 'Moon' },
  { name: 'system', label: '跟随系统', icon: 'Monitor' },
]
export const getTheme = (name) => THEMES[name] || THEMES.indigo
export const getSavedTheme = () => getTheme(localStorage.getItem(localStorage.getItem(STYLE_STORAGE_KEY) === 'classic' ? THEME_STORAGE_KEY : SIMPLE_THEME_STORAGE_KEY) || (localStorage.getItem(STYLE_STORAGE_KEY) === 'classic' ? 'indigo' : 'green'))
