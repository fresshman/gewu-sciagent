import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles/tokens.css";
import "./styles/global.css";

// 防主题闪烁：读取本地偏好，无则跟随系统
const stored = localStorage.getItem("gewu-theme");
const sysDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
document.documentElement.dataset.theme = stored || (sysDark ? "dark" : "light");

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
