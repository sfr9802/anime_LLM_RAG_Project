// layouts/MainLayout.tsx
import { useState } from "react";
import { useDarkMode } from "@/hooks/useDarkMode";
import { useAuth } from "@/contexts/AuthContext";
import Sidebar from "./Sidebar";
import "./MainLayout.css";
import "@/styles/components.css";

interface Props {
  children: React.ReactNode;
  minimal?: boolean; // ✅ 추가
}

export default function MainLayout({ children, minimal = false }: Props) {
  const [darkMode, setDarkMode] = useDarkMode();
  const { user, loading, logout } = useAuth();

  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    const saved = localStorage.getItem("sidebarCollapsed");
    if (saved !== null) return saved === "true";
    const isMobile = window.matchMedia("(max-width: 768px)").matches;
    return isMobile;
  });

  const toggleSidebar = () => {
    setSidebarCollapsed((prev) => {
      const next = !prev;
      localStorage.setItem("sidebarCollapsed", String(next));
      return next;
    });
  };

  return (
    <div className="layout-container">
      {!minimal && <Sidebar collapsed={sidebarCollapsed} />}

      <div className="main-area">
        {!minimal && (
          <header className="layout-header">
            <div className="left-controls">
              <button className="sidebar-toggle button-lala" onClick={toggleSidebar}>≡</button>
              <a href="/" className="logo" aria-label="홈으로 이동">
                GPT Clone
              </a>
            </div>

            <div className="auth-controls">
              <button className="button-lala" onClick={() => setDarkMode((prev) => !prev)}>
                {darkMode ? "☀️" : "🌙"}
              </button>

              {!loading && (
                user ? (
                  <>
                    <span className="username">{user.username}</span>
                    <button className="button-lala" onClick={logout}>로그아웃</button>
                  </>
                ) : (
                  <button className="button-lala" onClick={() => location.assign("/login")}>로그인</button>
                )
              )}
            </div>
          </header>
        )}

        <main className="layout-main">{children}</main>
      </div>
    </div>
  );
}
