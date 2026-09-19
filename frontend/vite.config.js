import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// GitHub Pages serves the project site from /<repo>/; BASE_PATH is set by the workflow.
export default defineConfig({
  base: process.env.BASE_PATH || "/",
  plugins: [react()],
});
