import { useEffect, useState } from "react";
import { getHealth } from "./api.js";
import Setup from "./screens/Setup.jsx";
import Session from "./screens/Session.jsx";
import Recap from "./screens/Recap.jsx";

// Where we are lives in the address bar, so reloading the page (or resizing
// it into a side panel) keeps you in place:
//   "#/session/abc123"        the session screen
//   "#/session/abc123/recap"  its recap
function routeFromHash() {
  const match = window.location.hash.match(/^#\/session\/([a-f0-9]+)(\/recap)?$/);
  if (!match) return { screen: "setup", sessionId: null };
  return { screen: match[2] ? "recap" : "session", sessionId: match[1] };
}

const BACKEND_DOWN = { title: "Nkuzi's backend isn't running.", fix: "In the backend folder, run: .\\run.ps1" };

// Asks the backend every 5 seconds whether everything is working.
// Returns {problems: [{title, fix}], gemmaReady: true/false}.
function useHealth() {
  const [health, setHealth] = useState({ problems: [], gemmaReady: true });

  useEffect(() => {
    let cancelled = false;

    async function check() {
      let next;
      try {
        const data = await getHealth();
        next = { problems: data.problems, gemmaReady: data.ollama_ok && data.model_present };
      } catch (e) {
        next = { problems: [BACKEND_DOWN], gemmaReady: false };
      }
      if (!cancelled) setHealth(next);
    }

    check();
    // Keep checking, so the banner goes away by itself once things are fixed.
    const timer = setInterval(check, 5000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  return health;
}

// Shows nothing when all is well. When something is broken, says what and how to fix it.
function ProblemBanner({ problems }) {
  if (problems.length === 0) return null;
  return (
    <div className="problems" role="alert">
      {problems.map((problem) => (
        <div key={problem.title} className="problem">
          <strong>{problem.title}</strong> {problem.fix}
        </div>
      ))}
    </div>
  );
}

// Three screens, no router needed: "setup" (home), "session" (outline +
// listening on one screen) and "recap".
export default function App() {
  const [route, setRoute] = useState(routeFromHash);

  // Back/forward buttons change the hash; follow them.
  useEffect(() => {
    const onHashChange = () => setRoute(routeFromHash());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const openSession = (id) => (window.location.hash = `#/session/${id}`);
  const openRecap = (id) => (window.location.hash = `#/session/${id}/recap`);
  const goHome = () => (window.location.hash = "");
  const { screen, sessionId } = route;
  const health = useHealth();
  // "Check me" needs Gemma. When it can't run, the button is disabled and says why.
  const checkBlocked = health.gemmaReady ? "" : health.problems[0]?.title || "Gemma isn't ready.";

  return (
    <div className="app">
      <ProblemBanner problems={health.problems} />
      <main className="main">
        {screen === "setup" && <Setup onCreated={openSession} />}
        {screen === "session" && (
          <Session
            key={sessionId}
            sessionId={sessionId}
            checkBlocked={checkBlocked}
            onBack={goHome}
            onEnd={() => openRecap(sessionId)}
          />
        )}
        {screen === "recap" && (
          <Recap key={sessionId} sessionId={sessionId} onBackToSession={() => openSession(sessionId)} onNewSession={goHome} />
        )}
      </main>
      <footer className="footer">Running offline · Gemma</footer>
    </div>
  );
}
