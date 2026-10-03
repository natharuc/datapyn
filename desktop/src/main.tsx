import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import {AppErrorBoundary} from "./AppErrorBoundary";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(<React.StrictMode><AppErrorBoundary><App /></AppErrorBoundary></React.StrictMode>);
