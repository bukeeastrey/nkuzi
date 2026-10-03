import { useEffect, useState } from "react";
import { getHealth } from "./api.js";
import Setup from "./screens/Setup.jsx";
import Session from "./screens/Session.jsx";

// The open session's id lives in the address bar ("#/session/abc123"), so
// reloading the page (or resizing it into a side panel) keeps you in place.
function sessionIdFromHash() {
  const match = window.location.hash.match(/^#\/session\/([a-f0-9]+)$/);
  return match ? match[1] : null;
}

// Shows nothing when all is well. When something is broken, says what and how to fix it.
function ProblemBanner() {
  const [problems, setProblems] = useState([]);

  useEffect(() => {
    let cancelled = false;

    async function check() {
      let found;
      try {
        found = (await getHealth()).problems;
      } catch (e) {
        found = [{ title: "Nkuzi's backend isn't running.", fix: "In the backend folder, run: .\\run.ps1" }];
      }
      if (!cancelled) setProblems(found);
    }

    check();
    // Keep checking, so the banner goes away by itself once things are fixed.
    const timer = setInterval(check, 5000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

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

// Two screens, no router needed: "setup" (home) and "session"
// (outline + listening on one screen). The recap arrives in a later milestone.
export default function App() {
  const [sessionId, setSessionId] = useState(sessionIdFromHash);

  // Back/forward buttons change the hash; follow them.
  useEffect(() => {
    const onHashChange = () => setSessionId(sessionIdFromHash());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  function openSession(id) {
    window.location.hash = `#/session/${id}`;
  }

  function goHome() {
    window.location.hash = "";
  }

  return (
    <div className="app">
      <ProblemBanner />
      <main className="main">
        {sessionId ? (
          <Session key={sessionId} sessionId={sessionId} onBack={goHome} />
        ) : (
          <Setup onCreated={openSession} />
        )}
      </main>
      <footer className="footer">Running offline · Gemma</footer>
    </div>
  );
}
