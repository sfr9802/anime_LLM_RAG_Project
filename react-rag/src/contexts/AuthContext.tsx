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

type MeResponse = {
  id: number;
  email: string;
  role: string;
  profile?: { id: number; nickname: string } | null;
};

interface User {
  id: number;
  username: string; // 프론트에서 쓰는 표시명
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

  const isAuthScreen = pathname.startsWith("/login") || pathname.startsWith("/oauth");
  const accessToken =
    typeof window !== "undefined" ? localStorage.getItem("accessToken") : null;

  const fetchMe = useCallback(async () => {
    try {
      const res = await axios.get<MeResponse>("/api/users/me");
      const d = res.data;
      const username =
        d.profile?.nickname ||
        (d.email ? d.email.split("@")[0] : `user-${d.id}`);
      setUser({
        id: d.id,
        email: d.email,
        role: d.role,
        username,
      });
    } catch (err) {
      console.warn("[Auth] /me API 호출 실패", err);
      setUser(null);
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      const t = localStorage.getItem("accessToken");
      localStorage.removeItem("accessToken");
      localStorage.removeItem("refreshToken");
      if (t) {
        await axios.post("/api/auth/logout", null, {
          headers: { Authorization: `Bearer ${t}` },
          withCredentials: true,
        });
      }
    } catch (err) {
      console.warn("🚨 로그아웃 요청 실패", err);
    }
    setUser(null);
    window.location.href = "/";
  }, []);

  useEffect(() => {
    if (isAuthScreen || !accessToken) {
      setLoading(false);
      setUser(null);
      if (isAuthScreen && accessToken) {
      window.location.replace("/");
      }
      return;
    }
    (async () => {
      setLoading(true);
      await fetchMe();
      setLoading(false);
    })();
  }, [isAuthScreen, accessToken, fetchMe]);

  const isAuthenticated = !!accessToken && (!!user || !isAuthScreen);

  const contextValue = useMemo(
    () => ({ user, loading, isAuthenticated, fetchMe, logout }),
    [user, loading, isAuthenticated, fetchMe, logout]
  );

  return (
    <AuthContext.Provider value={contextValue}>{children}</AuthContext.Provider>
  );
};
