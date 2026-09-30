import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { motion, useReducedMotion } from "motion/react";
import { BlurFade } from "./components/BlurFade";
import { BorderBeam } from "./components/BorderBeam";
import { DotPattern } from "./components/DotPattern";
import { MagicCard } from "./components/MagicCard";
import "./styles.css";

const actions = [
  {
    icon: "≡",
    title: "Summarize documents",
    note: "Grounded overview from indexed files",
    prompt: "Summarize the key points in my connected documents.",
  },
  {
    icon: "↥",
    title: "Analyze a file",
    note: "PDF, spreadsheet, code, and more",
    prompt: "Analyze the attached file and highlight the most important findings.",
  },
  {
    icon: "⇄",
    title: "Compare sources",
    note: "Find differences and shared themes",
    prompt: "Compare my selected sources and explain their key differences.",
  },
  {
    icon: "</>",
    title: "Review code",
    note: "Understand and improve code",
    prompt: "Review the attached code, explain it, and suggest concrete improvements.",
  },
];

function QuickActions() {
  const sendPrompt = (prompt: string) => {
    window.dispatchEvent(new CustomEvent("magicui:prompt", { detail: { prompt } }));
  };

  return (
    <div className="mui-quick-grid">
      {actions.map((action, index) => (
        <BlurFade key={action.title} delay={index * 0.055}>
          <MagicCard className="mui-action-card" gradientFrom={index % 2 ? "#3cc9b0" : "#7967ff"} gradientTo={index % 2 ? "#d16ba5" : "#3cc9b0"}>
            <button type="button" className="mui-action-button" onClick={() => sendPrompt(action.prompt)}>
              <span className="mui-action-icon">{action.icon}</span>
              <span>
                <strong>{action.title}</strong>
                <small>{action.note}</small>
              </span>
            </button>
          </MagicCard>
        </BlurFade>
      ))}
    </div>
  );
}

function NeuralMark() {
  const reduced = useReducedMotion();

  return (
    <BlurFade>
      <div className="mui-neural-mark" aria-hidden="true">
        <motion.span className="mui-orbit-dot" animate={reduced ? undefined : { rotate: 360 }} transition={{ repeat: Infinity, duration: 18, ease: "linear" }} />
        <motion.span className="mui-ring mui-ring-one" animate={reduced ? undefined : { rotate: 360 }} transition={{ repeat: Infinity, duration: 12, ease: "linear" }} />
        <motion.span className="mui-ring mui-ring-two" animate={reduced ? undefined : { rotate: -360 }} transition={{ repeat: Infinity, duration: 9, ease: "linear" }} />
        <span className="mui-core">S</span>
      </div>
    </BlurFade>
  );
}

function ComposerBeam() {
  const [sending, setSending] = useState(false);

  useEffect(() => {
    const update = (event: Event) => setSending(Boolean((event as CustomEvent<{ sending: boolean }>).detail?.sending));
    window.addEventListener("synapse:sending", update);
    return () => window.removeEventListener("synapse:sending", update);
  }, []);

  return (
    <div className={sending ? "mui-beam-active" : "mui-beam-idle"}>
      <BorderBeam duration={sending ? 2.8 : 8} colorFrom={sending ? "#3cc9b0" : "#7967ff"} colorTo="#d16ba5" borderWidth={sending ? 1.5 : 1} />
    </div>
  );
}

function mount(id: string, node: React.ReactNode) {
  const element = document.getElementById(id);
  if (element) createRoot(element).render(<StrictMode>{node}</StrictMode>);
}

function boot() {
  mount("magicui-root", <DotPattern width={28} height={28} cr={1.15} glow />);
  mount("magicWelcomeVisual", <NeuralMark />);
  mount("magicQuickActions", <QuickActions />);
  mount("magicComposerBeam", <ComposerBeam />);
  document.documentElement.dataset.magicui = "ready";
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot, { once: true });
else boot();
