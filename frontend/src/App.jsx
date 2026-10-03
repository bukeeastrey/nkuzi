import { useState } from "react";
import Setup from "./screens/Setup.jsx";
import OutlineReview from "./screens/OutlineReview.jsx";

// A tiny state machine instead of a router. Screens so far: "setup", "outline".
// Later milestones add "live" and "recap".
export default function App() {
  const [screen, setScreen] = useState("setup");
  const [session, setSession] = useState(null); // what POST /sessions returned

  function openOutline(newSession) {
    setSession(newSession);
    setScreen("outline");
  }

  function goHome() {
    setSession(null);
    setScreen("setup");
  }

  return (
    <div className="app">
      <main className="main">
        {screen === "setup" && <Setup onCreated={openOutline} />}
        {screen === "outline" && <OutlineReview session={session} onBack={goHome} />}
      </main>
      <footer className="footer">
        Runs 100% on this device · Gemma + Whisper · no internet needed
      </footer>
    </div>
  );
}
