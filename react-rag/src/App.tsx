import "./styles/gLobal.css"; // ✅ 글로벌 스타일은 최상단

import { BrowserRouter as Router } from "react-router-dom";
import { AuthProvider } from "./contexts/AuthContext"; // ✅ 경로 수정
import AppRoutes from "@/routes";

export default function App() {
  return (
    <Router>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </Router>
  );
}
