import axios from "@/libs/axios";
import {
  createContext,
  useState,
  useEffect,
  useCallback,
  useContext,
  useMemo,
} from "react";
import { useLocation } from "react-router-dom";

interface User {
  id: number;
  username: string;
  email: string;
  role: string;
}

interface AuthContextType {
  user: User | null;
  loading: boolean;
  isAuthenticated: boolean;
  fetchMe: () => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | null>(null);

export const useAuth = (): AuthContextType => {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
};

export const AuthProvider = ({ children }: { children: React.ReactNode }) => {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const { pathname } = useLocation();

  const isAuthScreen =
    pathname.startsWith("/login") || pathname.startsWith("/oauth");
  const accessToken =
    typeof window !== "undefined" ? localStorage.getItem("accessToken") : null;

  const fetchMe = useCallback(async () => {
    try {
      const res = await axios.get<User>("/api/users/me");
      setUser(res.data);
    } catch (err) {
      console.warn("[Auth] /me API 호출 실패", err);
      setUser(null);
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      const accessToken = localStorage.getItem("accessToken");
      localStorage.removeItem("accessToken");
      localStorage.removeItem("refreshToken");
      if (accessToken) {
        await axios.post("/api/auth/logout", null, {
          headers: { Authorization: `Bearer ${accessToken}` },
        });
      }
    } catch (err) {
      console.warn("🚨 로그아웃 요청 실패", err);
    }
    setUser(null);
    window.location.href = "/";
  }, []);

  // ✅ 핵심: 조건부로만 /me 호출
  useEffect(() => {
    // 인증 화면이거나 토큰 없으면 호출하지 않음
    if (isAuthScreen || !accessToken) {
      setLoading(false);
      setUser(null);
      return;
    }

    (async () => {
      setLoading(true);
      await fetchMe();
      setLoading(false);
    })();
  }, [isAuthScreen, accessToken, fetchMe]);

  // isAuthenticated는 토큰 존재 OR /me 결과로 판단 (깜빡임/초기화 방지)
  const isAuthenticated = !!accessToken && (!!user || !isAuthScreen);

  const contextValue = useMemo(
    () => ({ user, loading, isAuthenticated, fetchMe, logout }),
    [user, loading, isAuthenticated, fetchMe, logout]
  );

  return (
    <AuthContext.Provider value={contextValue}>{children}</AuthContext.Provider>
  );
};
