import React from "react";
import { createRoot } from "react-dom/client";
import "./styles/app.css";
import Landing from "./pages/Landing";
import Console from "./console/Console";

// Hash routing: GitHub Pages serves static files, so "#/console/runs" needs no server rewrite.
// A bare "#how" is an in-page anchor on the landing.
function useRoute() {
  const [hash, setHash] = React.useState(window.location.hash);
  React.useEffect(() => {
    const on = () => setHash(window.location.hash);
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return hash;
}

function App() {
  const hash = useRoute();
  const isConsole = hash.startsWith("#/console");
  React.useEffect(() => {
    if (isConsole || hash.startsWith("#/")) {
      window.scrollTo(0, 0);
    } else if (hash.length > 1) {
      document.getElementById(hash.slice(1))?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    document.title = isConsole ? "AngryRobot console" : "AngryRobot";
  }, [hash, isConsole]);
  if (isConsole) return <Console view={hash.split("/")[2] || "overview"} />;
  return <Landing />;
}

createRoot(document.getElementById("root")).render(<App />);
