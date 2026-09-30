const actions = [
  ["≡", "Summarize documents", "Grounded overview from indexed files", "Summarize the key points in my connected documents."],
  ["↥", "Analyze a file", "PDF, spreadsheet, code, and more", "Analyze the attached file and highlight the most important findings."],
  ["⇄", "Compare sources", "Find differences and shared themes", "Compare my selected sources and explain their key differences."],
  ["</>", "Review code", "Understand and improve code", "Review the attached code, explain it, and suggest concrete improvements."],
];

function mountDots() {
  const root = document.getElementById("magicui-root");
  if (!root) return;
  root.innerHTML = `<svg class="mui-dot-pattern" aria-hidden="true"><defs><pattern id="mui-dots" width="28" height="28" patternUnits="userSpaceOnUse"><circle cx="1.15" cy="1.15" r="1.15" fill="currentColor"/></pattern></defs><rect width="100%" height="100%" fill="url(#mui-dots)"/></svg>`;
}

function mountWelcomeVisual() {
  const root = document.getElementById("magicWelcomeVisual");
  if (!root) return;
  root.innerHTML = `<div class="mui-neural-mark" aria-hidden="true"><span class="mui-orbit-dot"></span><span class="mui-ring mui-ring-one"></span><span class="mui-ring mui-ring-two"></span><span class="mui-core">S</span></div>`;
}

function mountQuickActions() {
  const root = document.getElementById("magicQuickActions");
  if (!root) return;
  root.innerHTML = `<div class="mui-quick-grid">${actions.map(([icon, title, note, prompt], index) => `
    <div class="mui-magic-card mui-action-card" style="animation-delay:${index * 55}ms">
      <div class="mui-magic-glow"></div>
      <div class="mui-magic-content">
        <button type="button" class="mui-action-button" data-magic-prompt="${prompt.replace(/"/g, "&quot;")}">
          <span class="mui-action-icon">${icon}</span>
          <span><strong>${title}</strong><small>${note}</small></span>
        </button>
      </div>
    </div>`).join("")}</div>`;
  root.querySelectorAll("[data-magic-prompt]").forEach((button) => {
    button.addEventListener("click", () => {
      window.dispatchEvent(new CustomEvent("magicui:prompt", { detail: { prompt: button.dataset.magicPrompt } }));
    });
  });
}

function mountComposerBeam() {
  const root = document.getElementById("magicComposerBeam");
  if (!root) return;
  root.innerHTML = `<div class="mui-beam-idle"><div class="mui-border-beam" style="--beam-width:1px"><span class="mui-border-beam-light"></span></div></div>`;
  window.addEventListener("synapse:sending", (event) => {
    const beam = root.firstElementChild;
    if (!beam) return;
    beam.className = event.detail?.sending ? "mui-beam-active" : "mui-beam-idle";
  });
}

function boot() {
  mountDots();
  mountWelcomeVisual();
  mountQuickActions();
  mountComposerBeam();
  document.documentElement.dataset.magicui = "ready";
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot, { once: true });
else boot();
