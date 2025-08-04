import axios from "@/libs/axios";
import {
  createContext,
  useState,
  useEffect,
  useCallback,
  useContext,
  useMemo,
} from "react";

// 타입 선언
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

// Context 초기화
const AuthContext = createContext<AuthContextType | null>(null);

// ✅ useAuth 훅
export const useAuth = (): AuthContextType => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
};

// ✅ AuthProvider 컴포넌트
export const AuthProvider = ({ children }: { children: React.ReactNode }) => {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchMe = useCallback(async () => {
    setLoading(true);
    try {
      const res = await axios.get("/api/users/me");
      setUser(res.data);
    } catch (err) {
      console.warn("[Auth] /me API 호출 실패", err);
      setUser(null);
    } finally {
      setLoading(false);
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

  const isAuthenticated = !!user;

  const contextValue = useMemo(() => ({
    user,
    loading,
    isAuthenticated,
    fetchMe,
    logout,
  }), [user, loading, isAuthenticated, fetchMe, logout]);

  useEffect(() => {
    fetchMe();
  }, [fetchMe]);

  return (
    <AuthContext.Provider value={contextValue}>
      {children}
    </AuthContext.Provider>
  );
};
