/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Where the API is, when it is not on the application's own origin. Unset by default. */
  readonly VITE_API_BASE?: string;
  readonly VITE_API_MODE?: string;
}
