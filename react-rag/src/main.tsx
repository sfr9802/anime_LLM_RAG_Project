// src/main.tsx
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
// import "./styles/global.css"; // 필요 시 주석 해제
import "./styles/lalaland_st.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
