import { useState } from "react";
import Setup from "./screens/Setup.jsx";

// A tiny state machine instead of a router. Screens so far: "setup".
// Later milestones add "outline", "live" and "recap".
export default function App() {
  const [screen] = useState("setup");

  return (
    <div className="app">
      <main className="main">{screen === "setup" && <Setup />}</main>
      <footer className="footer">
        Runs 100% on this device · Gemma + Whisper · no internet needed
      </footer>
    </div>
  );
}
