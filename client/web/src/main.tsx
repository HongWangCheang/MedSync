import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { Controller } from "./core/controller";
import "./styles.css";

const root = createRoot(document.getElementById("root")!);
Controller.open().then(
  (controller) => root.render(<StrictMode><App controller={controller} /></StrictMode>),
  (error) => root.render(<p className="fatal">无法打开本机存储（IndexedDB）：{String(error)}</p>),
);
