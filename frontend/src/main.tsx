import "@fontsource-variable/plus-jakarta-sans";
import "@fontsource-variable/source-serif-4";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { liveApi, type Api } from "./api/client";
import "./styles.css";

// npm run dev:examples serves the committed example responses instead of calling the API. They are loaded only
// then, so the real application does not carry them.
const examples = import.meta.env.VITE_API_MODE === "examples";
const api: Promise<Api> = examples ? import("./api/examples").then((module) => module.exampleApi) : Promise.resolve(liveApi);

void api.then((chosen) => {
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App api={chosen} examples={examples} />
    </StrictMode>,
  );
});
