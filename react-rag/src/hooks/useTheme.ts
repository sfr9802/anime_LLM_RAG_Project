// hooks/useTheme.ts
import { useEffect, useState } from "react";

export function useTheme() {
  const [theme, setTheme] = useState(() => {
    return localStorage.getItem("theme") || "light";
  });

  useEffect(() => {
    const root = document.documentElement;
    root.classList.remove("dark", "lalaland_st");
    if (theme === "dark") {
      root.classList.add("dark");
    } else if (theme === "lalaland_st") {
      root.classList.add("lalaland_st");
    }
    localStorage.setItem("theme", theme);
  }, [theme]);

  return [theme, setTheme] as const;
}
