import "@fontsource-variable/archivo/wdth.css";
import "@fontsource-variable/source-serif-4";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { liveApi } from "./api/client";
import { exampleApi } from "./api/examples";
import "./styles.css";

// npm run dev:examples serves the committed example responses instead of calling the API.
const examples = import.meta.env.VITE_API_MODE === "examples";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App api={examples ? exampleApi : liveApi} examples={examples} />
  </StrictMode>,
);
