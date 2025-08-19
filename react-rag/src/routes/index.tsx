// routes/index.tsx
import { Routes, Route } from "react-router-dom";
import ChatPage from "@/features/chat/pages/ChatPage";
import LoginPage from "@/features/auth/pages/LoginPage";
import OAuthSuccessPopup from "@/features/auth/pages/OAuthSuccessPopup";
import MainLayout from "@/layouts/MainLayout";
import RequireAuth from "./requireAuth";

export default function AppRoutes() {
  return (
    <Routes>
      {/* 공개 */}
      <Route
        path="/login"
        element={
          <MainLayout minimal>
            <LoginPage />
          </MainLayout>
        }
      />
      {/* 팝업 페이지는 레이아웃 없이 */}
      <Route path="/oauth/success-popup" element={<OAuthSuccessPopup />} />

      {/* 보호 */}
      <Route
        path="/"
        element={
          <RequireAuth>
            <MainLayout>
              <ChatPage />
            </MainLayout>
          </RequireAuth>
        }
      />
    </Routes>
  );
}
