export const THEME_STORAGE_KEY = 'jjc_theme'

export const THEMES = {
  indigo: { name: 'indigo', label: '默认靛蓝', primary: '#5e6ad2', strong: '#4f5bc4', soft: '#eef0ff', softStrong: '#d8dbfb', secondary: '#8b93e8', pale: '#cdd1ff' },
  rose: { name: 'rose', label: '品牌玫红', primary: '#e61d4f', strong: '#c8103f', soft: '#fff0f4', softStrong: '#ffe2ea', secondary: '#f07a96', pale: '#fecdd3' },
  green: { name: 'green', label: '库存绿色', primary: '#4f7f2d', strong: '#315e1b', soft: '#f0f5ec', softStrong: '#dce8d3', secondary: '#9fbd55', pale: '#c7d6a4' },
}

export const THEME_OPTIONS = Object.values(THEMES)
export const getTheme = (name) => THEMES[name] || THEMES.indigo
export const getSavedTheme = () => getTheme(localStorage.getItem(THEME_STORAGE_KEY))
