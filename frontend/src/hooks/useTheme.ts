import { useCallback, useEffect, useState } from 'react'

const STORAGE_KEY = 'rollcall-theme'

type Theme = 'dark' | 'light'

// index.html ships with class="dark" on <html> so the first paint is dark;
// this hook only has to remove it when the stored preference is light.
export function useTheme() {
  const [theme, setTheme] = useState<Theme>(() =>
    (localStorage.getItem(STORAGE_KEY) as Theme) || 'dark'
  )

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark')
    localStorage.setItem(STORAGE_KEY, theme)
  }, [theme])

  const toggleTheme = useCallback(() => {
    setTheme(t => (t === 'dark' ? 'light' : 'dark'))
  }, [])

  return { theme, toggleTheme }
}
