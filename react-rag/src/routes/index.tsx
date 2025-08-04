import { Routes, Route } from "react-router-dom";
import ChatPage from "@/features/chat/pages/ChatPage";
import LoginPage from "@/features/auth/pages/LoginPage";
import MainLayout from "@/layouts/MainLayout";
import RequireAuth from "./requireAuth";

export default function AppRoutes() {
  return (
    <Routes>
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
      <Route
        path="/login"
        element={
          <MainLayout>
            <LoginPage />
          </MainLayout>
        }
      />
    </Routes>
  );
}
