// src/routes/index.tsx
import { createBrowserRouter } from 'react-router-dom';
import ChatPage from '@/features/chat/pages/ChatPage';

export const router = createBrowserRouter([
  {
    path: '/',
    element: <ChatPage />,
  },
]);
