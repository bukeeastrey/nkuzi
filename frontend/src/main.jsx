import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import { APP_NAME } from "./config.js";
import "./styles.css";

document.title = APP_NAME;

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
