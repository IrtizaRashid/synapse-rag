"use client";
import {
  FormEvent,
  ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  ArrowDownToLine,
  ArrowRight,
  BookOpen,
  Bot as BotIcon,
  Check,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  Copy,
  FileText,
  Globe,
  Layers,
  Loader2,
  LogOut,
  Menu,
  MessageSquare,
  Moon,
  Pencil,
  Plus,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  Sun,
  Trash2,
  Upload,
  X,
  FlaskConical,
  RefreshCw,
} from "lucide-react";
import {
  api,
  Bot,
  BotPayload,
  Conversation,
  FileItem,
  formatBytes,
  formatDate,
  jsonBody,
  SourceHit,
  User,
} from "@/lib/api";
type View =
  "overview" | "knowledge" | "chat" | "assistants" | "retrieval" | "settings";
type Preview = { title: string; content: string; file?: FileItem };
type QueuedMessage = { id: string; content: string; botIds: string[] };
type Health = {
  database: string;
  retrieval: string;
  generation: string;
  max_upload_mb: number;
};
const nav = [
  { id: "chat", label: "Chats", icon: MessageSquare, target: "chat" },
  { id: "assistants", label: "Assistants", icon: BotIcon, target: "assistants" },
  { id: "knowledge", label: "Knowledge Base", icon: BookOpen, target: "knowledge" },
  { id: "documents", label: "Documents", icon: FileText, target: "knowledge" },
] as const;
const blank: BotPayload = {
  name: "",
  description: "",
  instructions:
    "Answer using the assigned sources. Cite evidence and say when the sources do not contain an answer.",
  sources: [],
  enabled: true,
  avatar: "S",
  color: "#3267e3",
};
export function Studio() {
  const [user, U] = useState<User | null>(null),
    [files, F] = useState<FileItem[]>([]),
    [bots, B] = useState<Bot[]>([]),
    [chats, C] = useState<Conversation[]>([]),
    [chat, SC] = useState<Conversation | null>(null);
  const [view, V] = useState<View>("assistants"),
    [busy, SB] = useState(""),
    [error, E] = useState(""),
    [toast, T] = useState("");
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [query, Q] = useState(""),
    [status, SS] = useState("all"),
    [modal, M] = useState<"upload" | "bot" | null>(null),
    [preview, P] = useState<Preview | null>(null);
  const [draft, D] = useState<BotPayload>(blank),
    [editId, EI] = useState<string | null>(null),
    [active, A] = useState<string[]>([]),
    [message, SM] = useState("");
  const [queued, SQ] = useState<QueuedMessage[]>([]);
  const [url, SU] = useState(""),
    [uploadTab, UT] = useState("file"),
    [mobile, MO] = useState(false),
    [collapsed, setCollapsed] = useState(false),
    [testQuery, TQ] = useState(""),
    [topK, TK] = useState(5),
    [testSource, TS] = useState("");
  const [result, R] = useState<{
      sources: SourceHit[];
      elapsed: number;
    } | null>(null),
    [health, H] = useState<Health | null>(null);
  const input = useRef<HTMLInputElement>(null),
    messagePane = useRef<HTMLDivElement>(null),
    lock = useRef(false),
    draining = useRef(false),
    queueRef = useRef<QueuedMessage[]>([]),
    chatRef = useRef<Conversation | null>(null);
  const ready = files.filter((f) => f.status === "ready"),
    shown = files.filter(
      (f) =>
        (status === "all" || f.status === status) &&
        `${f.name} ${f.source}`.toLowerCase().includes(query.toLowerCase()),
    );
  const recentChats = chats.slice(0, 5);
  const sourceName = useCallback(
    (source: string) => files.find((f) => f.source === source)?.name || source,
    [files],
  );
  const refresh = useCallback(async () => {
    const [f, b, c] = await Promise.all([
      api<{ files: FileItem[] }>("/api/files"),
      api<{ chatbots: Bot[] }>("/api/chatbots"),
      api<{ conversations: Conversation[] }>("/api/conversations"),
    ]);
    F(f.files);
    B(b.chatbots);
    C(c.conversations);
  }, []);
  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const me = await api<{ user: User }>("/api/auth/me");
        if (!alive) return;
        U(me.user);
        await refresh();
        const h = await api<Health>("/api/workspace/status");
        if (alive) H(h);
      } catch (e) {
        if (alive)
          E(e instanceof Error ? e.message : "Unable to open workspace");
      }
    })();
    return () => {
      alive = false;
    };
  }, [refresh]);
  useEffect(() => {
    const stored = window.localStorage.getItem("synapse-theme");
    const prefersDark = window.matchMedia?.("(prefers-color-scheme: dark)").matches;
    const next =
      stored === "dark" || stored === "light"
        ? stored
        : prefersDark
          ? "dark"
          : "light";
    setTheme(next);
    document.documentElement.dataset.theme = next;
  }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem("synapse-theme", theme);
  }, [theme]);
  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => T(""), 5000);
    return () => clearTimeout(id);
  }, [toast]);
  useEffect(() => {
    if (!files.some((f) => f.status === "processing")) return;
    const id = setInterval(() => {
      void refresh();
    }, 2500);
    return () => clearInterval(id);
  }, [files, refresh]);
  useEffect(() => {
    const pane = messagePane.current;
    if (!pane) return;
    requestAnimationFrame(() => {
      pane.scrollTo({ top: pane.scrollHeight, behavior: "smooth" });
    });
  }, [chat?.messages, busy, queued.length]);
  useEffect(() => {
    chatRef.current = chat;
  }, [chat]);
  function go(v: View) {
    V(v);
    MO(false);
    Q("");
    E("");
  }
  async function run(label: string, fn: () => Promise<void>) {
    if (lock.current) return;
    lock.current = true;
    SB(label);
    E("");
    try {
      await fn();
    } catch (e) {
      E(
        e instanceof Error
          ? e.message
          : "The request failed. Please try again.",
      );
    } finally {
      lock.current = false;
      SB("");
    }
  }
  function edit(bot?: Bot) {
    EI(bot ? String(bot.id) : null);
    D(
      bot
        ? {
            ...blank,
            name: bot.name,
            description: bot.description || "",
            instructions: bot.instructions || "",
            sources: bot.sources,
            enabled: bot.enabled !== false,
            color: bot.color || blank.color,
            avatar: bot.avatar || "S",
          }
        : { ...blank, sources: ready.map((f) => f.source) },
    );
    M("bot");
  }
  async function upload(selected: File[]) {
    if (!selected.length) return;
    await run("Saving documents", async () => {
      const body = new FormData();
      selected.forEach((f) => body.append("files", f));
      const r = await api<{
        results: { source: string; status: string; error?: string }[];
      }>("/api/ingest/files", { method: "POST", body });
      await refresh();
      M(null);
      go("knowledge");
      const failed = r.results.filter((f) => f.status === "error");
      const queued = r.results.filter((f) => f.status === "queued");
      T(
        queued.length
          ? `${queued.length} document(s) queued for background indexing`
          : `${r.results.length - failed.length} document(s) saved`,
      );
      if (failed.length)
        E(failed.map((f) => `${f.source}: ${f.error}`).join(" · "));
    });
  }
  async function importUrl(e: FormEvent) {
    e.preventDefault();
    await run("Importing web page", async () => {
      await api("/api/ingest/url", { method: "POST", body: jsonBody({ url }) });
      await refresh();
      SU("");
      M(null);
      go("knowledge");
      T("Web page added");
    });
  }
  async function save(e: FormEvent) {
    e.preventDefault();
    await run("Saving assistant", async () => {
      await api(editId ? `/api/chatbots/${editId}` : "/api/chatbots", {
        method: editId ? "PATCH" : "POST",
        body: jsonBody(draft),
      });
      await refresh();
      M(null);
      T("Assistant saved");
    });
  }
  async function openChat(id: string) {
    await run("Opening conversation", async () => {
      const r = await api<{ conversation: Conversation }>(
        `/api/conversations/${id}`,
      );
      SC(r.conversation);
      A(r.conversation.bot_ids);
      go("chat");
    });
  }
  function newChat(bot?: Bot) {
    SC(null);
    chatRef.current = null;
    SM("");
    A(
      bot
        ? [String(bot.id)]
        : bots
            .filter((b) => b.enabled !== false)
            .slice(0, 1)
            .map((b) => String(b.id)),
    );
    go("chat");
  }
  function send(e: FormEvent) {
    e.preventDefault();
    const content = message.trim();
    if (!content) return;
    if (!active.length) {
      E(
        bots.length
          ? "Choose an assistant before sending."
          : "Create an assistant before sending your first message.",
      );
      return;
    }
    const item: QueuedMessage = {
      id:
        typeof crypto !== "undefined" && "randomUUID" in crypto
          ? crypto.randomUUID()
          : `${Date.now()}-${Math.random()}`,
      content,
      botIds: [...active],
    };
    queueRef.current = [...queueRef.current, item];
    SQ(queueRef.current);
    SM("");
    void drainQueue();
  }
  async function drainQueue() {
    if (draining.current) return;
    draining.current = true;
    E("");
    try {
      while (queueRef.current.length) {
        const item = queueRef.current[0];
        SB(
          queueRef.current.length > 1
            ? `Answering 1 of ${queueRef.current.length} queued messages`
            : "Finding evidence and preparing your answer",
        );
        let target = chatRef.current;
        if (!target) {
          const r = await api<{ conversation: Conversation }>(
            "/api/conversations",
            {
              method: "POST",
              body: jsonBody({
                title: item.content.slice(0, 72) || "New conversation",
                bot_ids: item.botIds,
              }),
            },
          );
          target = r.conversation;
          chatRef.current = target;
          SC(target);
        }
        const r = await api<{ conversation: Conversation }>(
          `/api/conversations/${target.id}/messages`,
          {
            method: "POST",
            body: jsonBody({ content: item.content, bot_ids: item.botIds }),
          },
        );
        chatRef.current = r.conversation;
        SC(r.conversation);
        queueRef.current = queueRef.current.slice(1);
        SQ(queueRef.current);
        await refresh();
      }
    } catch (e) {
      E(e instanceof Error ? e.message : "The request failed. Please try again.");
    } finally {
      draining.current = false;
      SB("");
    }
  }
  async function remove(f: FileItem) {
    if (!confirm(`Delete ${f.name} and its indexed passages?`)) return;
    await run("Deleting document", async () => {
      await api(`/api/files/${f.id}`, { method: "DELETE" });
      await refresh();
      T("Document deleted");
    });
  }
  async function rename(f: FileItem) {
    const name = prompt("Document name", f.name);
    if (!name?.trim() || name === f.name) return;
    await run("Renaming document", async () => {
      await api(`/api/files/${f.id}`, {
        method: "PATCH",
        body: jsonBody({ name: name.trim() }),
      });
      await refresh();
    });
  }
  async function inspect(f: FileItem) {
    await run("Opening source", async () => {
      const r = await api<{ content: string }>(`/api/files/${f.id}/preview`);
      P({ title: f.name, content: r.content, file: f });
    });
  }
  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      T("Copied to clipboard");
    } catch {
      E("Clipboard access is unavailable in this browser.");
    }
  }
  function exportChat() {
    if (!chat) return;
    const text =
      `# ${chat.title}\n\n` +
      (chat.messages || [])
        .map(
          (m) =>
            `## ${m.role === "user" ? "You" : m.bot_name || "Assistant"}\n\n${m.content}\n\n` +
            (m.sources || [])
              .map(
                (s) =>
                  `- [${s.number}] ${s.source} — ${s.location}\n${s.preview || ""}`,
              )
              .join("\n"),
        )
        .join("\n\n");
    const a = document.createElement("a"),
      href = URL.createObjectURL(new Blob([text], { type: "text/markdown" }));
    a.href = href;
    a.download = "synapse-conversation.md";
    a.click();
    URL.revokeObjectURL(href);
  }
  async function test(e: FormEvent) {
    e.preventDefault();
    await run("Testing retrieval", async () => {
      const start = performance.now(),
        r = await api<{ sources: SourceHit[] }>("/api/retrieval/test", {
          method: "POST",
          body: jsonBody({
            question: testQuery,
            top_k: topK,
            sources: testSource ? [testSource] : null,
          }),
        });
      R({ ...r, elapsed: Math.round(performance.now() - start) });
    });
  }
  const sourceCards = (sources: SourceHit[]) => (
    <details className="sources-disclosure">
      <summary>
        <span>
          <BookOpen size={14} />
          Sources
        </span>
        <strong>{sources.length}</strong>
      </summary>
      <div className="source-cards">
        {sources.map((s, i) => (
          <button
            className="source-card"
            key={i}
            onClick={() =>
              P({
                title: s.source,
                content: `${s.location || "Source passage"}\n\n${s.preview || ""}`,
              })
            }
          >
            <span className="source-number">{s.number || i + 1}</span>
            <div>
              <strong>{s.source}</strong>
              <small>{s.location || "Indexed passage"}</small>
              {s.preview && <p>{s.preview}</p>}
            </div>
            <ChevronRight size={14} />
          </button>
        ))}
      </div>
    </details>
  );
  return (
    <div className={`studio-shell ${collapsed ? "sidebar-collapsed" : ""}`}>
      {mobile && (
        <button
          className="mobile-shade"
          aria-label="Close navigation"
          onClick={() => MO(false)}
        />
      )}
      <aside className={`studio-sidebar ${mobile ? "is-open" : ""}`}>
        <a href="/" className="studio-brand">
          <span className="brand-mark">
            <Layers size={23} />
          </span>
          <span className="brand-word">synapse<span className="brand-dot">.</span></span>
        </a>
        <button
          className="sidebar-collapse"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          onClick={() => setCollapsed((value) => !value)}
        >
          {collapsed ? <ChevronsRight size={16} /> : <ChevronsLeft size={16} />}
        </button>
        <button className="new-chat-button" onClick={() => newChat()}>
          <Plus size={18} />
          New chat
        </button>
        <nav>
          {nav.map((n) => (
            <button
              key={n.id}
              className={`nav-item ${view === n.target ? "active" : ""}`}
              onClick={() => go(n.target)}
              title={n.label}
            >
              <n.icon size={18} />
              <span className="nav-text">{n.label}</span>
              {n.id === "knowledge" && (
                <span className="nav-count">{files.length}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="recent-chats">
          <div className="recent-label">
            <span className="nav-text">Recent chats</span>
          </div>
          {recentChats.length ? (
            recentChats.map((c) => (
              <button key={c.id} onClick={() => openChat(c.id)}>
                <MessageSquare size={14} />
                <span className="nav-text">{c.title}</span>
              </button>
            ))
          ) : (
            <p>No chats yet</p>
          )}
        </div>
        <div className="sidebar-bottom">
          <button
            className="nav-item"
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
          >
            {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
            <span className="nav-text">{theme === "dark" ? "Light mode" : "Dark mode"}</span>
          </button>
          <button className="nav-item" onClick={() => go("settings")}>
            <Settings2 size={18} />
            Settings
          </button>
          <div className="profile">
            <span className="profile-avatar">
              {user?.name?.[0]?.toUpperCase() || "S"}
            </span>
            <div>
              <strong>{user?.name || "Loading workspace…"}</strong>
              <small>{user?.email || "Connecting securely"}</small>
            </div>
            <button
              aria-label="Log out"
              onClick={() =>
                run("Signing out", async () => {
                  await api("/api/auth/logout", { method: "POST" });
                  window.location.href = "/login";
                })
              }
            >
              <LogOut size={16} />
            </button>
          </div>
        </div>
      </aside>
      <main className="studio-main">
        <header className="studio-header">
          <div className="breadcrumbs">
            <button
              className="mobile-toggle"
              aria-label="Open navigation"
              onClick={() => MO(true)}
            >
              <Menu size={20} />
            </button>
            <span>Workspace</span>
            <ChevronRight size={14} />
            <strong>
              {nav.find((n) => n.target === view)?.label || "Settings"}
            </strong>
          </div>
          <div className="header-right">
            <span className="profile-avatar small">
              {user?.name?.[0]?.toUpperCase() || "S"}
            </span>
          </div>
        </header>
        {error && (
          <div className="error-banner" role="alert">
            <span>{error}</span>
            <button aria-label="Dismiss error" onClick={() => E("")}>
              <X size={16} />
            </button>
          </div>
        )}
        {busy && (
          <div className="progress-banner" role="status">
            <Loader2 size={15} className="spin" />
            {busy}…
          </div>
        )}
        <div
          className={`studio-content ${view === "chat" ? "chat-content" : ""}`}
        >
          {view === "overview" && (
            <>
              <div className="page-heading">
                <div>
                  <p className="eyebrow">YOUR KNOWLEDGE, CONNECTED</p>
                  <h1>A little clarity goes a long way.</h1>
                  <p>
                    Turn your documents into answers you can trace and trust.
                  </p>
                </div>
                <button className="primary" onClick={() => M("upload")}>
                  <Plus size={17} />
                  Upload document
                </button>
              </div>
              <div className="overview-hero">
                <div>
                  <span className="hero-kicker">
                    <Sparkles size={15} />
                    FROM INFORMATION TO UNDERSTANDING
                  </span>
                  <h2>
                    Good answers start
                    <br />
                    with your knowledge.
                  </h2>
                  <p>
                    Bring your files together, give your assistants context,
                    <br className="desktop-break" /> and find the answer with
                    the evidence beside it.
                  </p>
                  <button className="primary" onClick={() => newChat()}>
                    Start a conversation
                    <ArrowRight size={16} />
                  </button>
                </div>
                <div className="knowledge-map" aria-hidden="true">
                  <div className="map-line line-a" />
                  <div className="map-line line-b" />
                  <div className="map-line line-c" />
                  <div className="map-source map-one">
                    <FileText size={20} />
                    <div>
                      <strong>Documents</strong>
                      <small>Your source of truth</small>
                    </div>
                  </div>
                  <div className="map-source map-two">
                    <Globe size={20} />
                    <div>
                      <strong>Web pages</strong>
                      <small>Context from the web</small>
                    </div>
                  </div>
                  <div className="map-core">
                    <Layers size={31} />
                  </div>
                  <div className="map-answer">
                    <span>
                      <Sparkles size={16} />
                      Grounded answer
                    </span>
                    <i />
                    <i />
                    <i />
                    <div>
                      <b>1</b>
                      <b>2</b>
                      <small>Sources included</small>
                    </div>
                  </div>
                </div>
              </div>
              <div className="metric-grid">
                {[
                  {
                    label: "Knowledge sources",
                    value: files.length,
                    icon: BookOpen,
                    note: `${ready.length} ready to use`,
                  },
                  {
                    label: "Indexed passages",
                    value: files.reduce((a, f) => a + (f.chunks || 0), 0),
                    icon: Layers,
                    note: "Searchable document context",
                  },
                  {
                    label: "Your assistants",
                    value: bots.length,
                    icon: BotIcon,
                    note: `${bots.filter((b) => b.enabled !== false).length} enabled`,
                  },
                  {
                    label: "Conversations",
                    value: chats.length,
                    icon: MessageSquare,
                    note: "Saved to your workspace",
                  },
                ].map((m) => (
                  <div className="metric" key={m.label}>
                    <div>
                      <span>{m.label}</span>
                      <m.icon size={18} />
                    </div>
                    <strong>{m.value.toLocaleString()}</strong>
                    <small>{m.note}</small>
                  </div>
                ))}
              </div>
              <div className="overview-columns">
                <section className="surface">
                  <div className="section-heading">
                    <div>
                      <h2>Recent knowledge</h2>
                      <p>The context behind your next answer.</p>
                    </div>
                    <button
                      className="text-button"
                      onClick={() => go("knowledge")}
                    >
                      View all
                      <ArrowRight size={14} />
                    </button>
                  </div>
                  {files.length ? (
                    files.slice(0, 4).map((f) => (
                      <button
                        className="document-row"
                        key={f.id}
                        onClick={() => inspect(f)}
                      >
                        <Badge file={f} />
                        <div>
                          <strong>{f.name}</strong>
                          <small>
                            {f.chunks || 0} passages ·{" "}
                            {formatDate(f.created_at)}
                          </small>
                        </div>
                        <Status value={f.status || "ready"} />
                        <ChevronRight size={16} />
                      </button>
                    ))
                  ) : (
                    <Empty
                      icon={<BookOpen />}
                      title="Your knowledge starts here"
                      text="Add a document or a web page. We’ll make it searchable."
                      action={
                        <button
                          className="secondary"
                          onClick={() => M("upload")}
                        >
                          <Plus size={15} />
                          Add your first source
                        </button>
                      }
                    />
                  )}
                </section>
                <section className="surface quick-guide">
                  <span className="guide-icon">
                    <Sparkles size={22} />
                  </span>
                  <h2>From source to certainty</h2>
                  <p>Three steps to your first grounded answer.</p>
                  {[
                    {
                      t: "Add your knowledge",
                      d: "Upload files or import a web page.",
                      done: !!ready.length,
                      action: () => M("upload"),
                    },
                    {
                      t: "Create an assistant",
                      d: "Choose the files it can read.",
                      done: !!bots.length,
                      action: () => edit(),
                    },
                    {
                      t: "Ask your first question",
                      d: "Open the citations. Check the evidence.",
                      done: !!chats.length,
                      action: () => newChat(),
                    },
                  ].map((s, i) => (
                    <button className="guide-step" key={s.t} onClick={s.action}>
                      <span className={s.done ? "step-done" : ""}>
                        {s.done ? <Check size={15} /> : i + 1}
                      </span>
                      <div>
                        <strong>{s.t}</strong>
                        <small>{s.d}</small>
                      </div>
                      <ChevronRight size={15} />
                    </button>
                  ))}
                </section>
              </div>
            </>
          )}
          {view === "knowledge" && (
            <>
              <Heading
                title="Knowledge Base"
                text="Upload documents your assistants can use to answer questions."
                action={
                  <button className="primary" onClick={() => M("upload")}>
                    <Plus size={17} />
                    Upload document
                  </button>
                }
              />
              <div className="library-summary">
                <BookOpen size={21} />
                <div>
                  <strong>{files.length} sources in your workspace</strong>
                  <span>
                    {ready.length} ready ·{" "}
                    {files.reduce((a, f) => a + (f.chunks || 0), 0)} indexed
                    passages ·{" "}
                    {formatBytes(
                      files.reduce((a, f) => a + (f.size_bytes || 0), 0),
                    )}{" "}
                    stored
                  </span>
                </div>
                <span className="tag">Private knowledge base</span>
              </div>
              <div className="table-toolbar">
                <div className="filter-tabs">
                  {["all", "ready", "error"].map((s) => (
                    <button
                      key={s}
                      className={status === s ? "selected" : ""}
                      onClick={() => SS(s)}
                    >
                      {s === "all"
                        ? "All sources"
                        : s === "ready"
                          ? "Ready"
                          : "Needs attention"}
                    </button>
                  ))}
                </div>
                <label className="search-input">
                  <Search size={16} />
                  <input
                    aria-label="Search documents"
                    placeholder="Search knowledge…"
                    value={query}
                    onChange={(e) => Q(e.target.value)}
                  />
                </label>
              </div>
              <div className="surface document-table">
                <div className="table-head">
                  <span>NAME</span>
                  <span>STATUS</span>
                  <span>PASSAGES</span>
                  <span>ADDED</span>
                  <span>ACTIONS</span>
                </div>
                {shown.map((f) => (
                  <div className="table-row" key={f.id}>
                    <button className="file-name" onClick={() => inspect(f)}>
                      <Badge file={f} />
                      <div>
                        <strong>{f.name}</strong>
                        <small>
                          {f.mime_type === "text/html"
                            ? "Web page"
                            : formatBytes(f.size_bytes)}
                          {f.bots?.length
                            ? ` · ${f.bots.length} assistant(s)`
                            : ""}
                        </small>
                      </div>
                    </button>
                    <Status value={f.status || "ready"} />
                    <span className="data-number">{f.chunks || 0}</span>
                    <span className="date-cell">
                      {formatDate(f.created_at)}
                    </span>
                    <div className="row-actions">
                      <button title="Rename document" onClick={() => rename(f)}>
                        <Pencil size={15} />
                      </button>
                      <button title="Delete document" onClick={() => remove(f)}>
                        <Trash2 size={15} />
                      </button>
                    </div>
                  </div>
                ))}
                {!shown.length && (
                  <Empty
                    icon={<BookOpen />}
                    title={
                      query
                        ? "No matching sources"
                        : "Give your workspace some context"
                    }
                    text={
                      query
                        ? "Try another search or change the status filter."
                        : "Upload a PDF, document, spreadsheet, image, or web page to get started."
                    }
                    action={
                      !query && (
                        <button className="primary" onClick={() => M("upload")}>
                          Upload document
                          <Plus size={16} />
                        </button>
                      )
                    }
                  />
                )}
              </div>
              <p className="library-footnote">
                <ShieldCheck size={14} />
                Sources are available only to your account and the assistants you
                assign them to.
              </p>
            </>
          )}
          {view === "assistants" && (
            <>
              <Heading
                title="Assistants"
                text="Create focused AI assistants and choose which documents each one can read."
                action={
                  <button className="primary" onClick={() => edit()}>
                    <Plus size={17} />
                    Create assistant
                  </button>
                }
              />
              <div className="assistant-grid">
                {bots.map((b) => (
                  <section className="surface assistant-card" key={b.id}>
                    <div className="assistant-card-top">
                      <span
                        className="assistant-icon"
                        style={{ color: b.color }}
                      >
                        <BotIcon size={25} />
                      </span>
                      <Status
                        value={b.enabled !== false ? "ready" : "disabled"}
                      />
                      <button title="Edit assistant" onClick={() => edit(b)}>
                        <Pencil size={17} />
                      </button>
                    </div>
                    <h2>{b.name}</h2>
                    <p>
                      {b.description || "A focused assistant for your knowledge."}
                    </p>
                    <span className="assistant-sources">
                      <BookOpen size={14} />
                      {b.sources.length} file{b.sources.length === 1 ? "" : "s"}{" "}
                      assigned
                    </span>
                    <div className="assigned-files">
                      {b.sources.length ? (
                        b.sources.slice(0, 4).map((source) => (
                          <span key={source}>
                            <FileText size={12} />
                            {sourceName(source)}
                          </span>
                        ))
                      ) : (
                        <span>
                          <FileText size={12} />
                          No files selected
                        </span>
                      )}
                      {b.sources.length > 4 && (
                        <small>+{b.sources.length - 4} more</small>
                      )}
                    </div>
                    <div className="assistant-card-actions">
                      <button
                        className="secondary"
                        disabled={b.enabled === false}
                        onClick={() => newChat(b)}
                      >
                        Chat with this assistant
                        <ArrowRight size={15} />
                      </button>
                      <button
                        title="Delete assistant"
                        onClick={() => {
                          if (confirm(`Delete ${b.name}?`))
                            void run("Deleting assistant", async () => {
                              await api(`/api/chatbots/${b.id}`, {
                                method: "DELETE",
                              });
                              await refresh();
                            });
                        }}
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>
                  </section>
                ))}
                <button className="assistant-create" onClick={() => edit()}>
                  <span>
                    <Plus size={25} />
                  </span>
                  <strong>Create an assistant</strong>
                </button>
              </div>
            </>
          )}
          {view === "chat" && (
            <div className="conversation-layout">
              <aside className="conversation-list">
                <div>
                  <h2>Conversations</h2>
                  <button
                    aria-label="New conversation"
                    onClick={() => newChat()}
                  >
                    <Plus size={18} />
                  </button>
                </div>
                <label className="search-input">
                  <Search size={15} />
                  <input
                    aria-label="Search conversations"
                    placeholder="Search conversations"
                    value={query}
                    onChange={(e) => Q(e.target.value)}
                  />
                </label>
                {chats
                  .filter((c) =>
                    c.title.toLowerCase().includes(query.toLowerCase()),
                  )
                  .map((c) => (
                    <div
                      className={`conversation-link ${chat?.id === c.id ? "selected" : ""}`}
                      key={c.id}
                    >
                      <button onClick={() => openChat(c.id)}>
                        <strong>{c.title}</strong>
                        <small>{formatDate(c.updated_at)}</small>
                      </button>
                      <button
                        title="Delete conversation"
                        onClick={() => {
                          if (confirm(`Delete conversation “${c.title}”?`))
                            void run("Deleting conversation", async () => {
                              await api(`/api/conversations/${c.id}`, {
                                method: "DELETE",
                              });
                              if (chat?.id === c.id) SC(null);
                              await refresh();
                            });
                        }}
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  ))}
                {!chats.length && (
                  <p className="muted">
                    Start a conversation. It will be saved here.
                  </p>
                )}
              </aside>
              <section className="chat-panel">
                <div className="chat-top">
                  <div>
                    <span className="assistant-icon small">
                      <Sparkles size={18} />
                    </span>
                    <strong>{chat?.title || "New conversation"}</strong>
                  </div>
                  <button
                    title="Export conversation"
                    disabled={!chat?.messages?.length}
                    onClick={exportChat}
                  >
                    <ArrowDownToLine size={18} />
                  </button>
                </div>
                <div className="chat-messages" ref={messagePane}>
                  {!chat?.messages?.length && (
                    <div className="chat-welcome">
                      <span className="welcome-logo">
                        <Layers size={31} />
                      </span>
                      <h2>Ask your assistant</h2>
                      <div className="suggestion-grid">
                        {[
                          "Summarize the key points in my documents",
                          "What are the main recommendations?",
                          "Compare the information across my sources",
                          "List action items",
                        ].map((s) => (
                          <button key={s} onClick={() => SM(s)}>
                            <MessageSquare size={17} />
                            <span>{s}</span>
                            <ArrowRight size={15} />
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                  {chat?.messages?.map((m) => (
                    <article className={`chat-message ${m.role}`} key={m.id}>
                      <span className="message-avatar">
                        {m.role === "user" ? (
                          user?.name?.[0]
                        ) : (
                          <Sparkles size={17} />
                        )}
                      </span>
                      <div className="message-body">
                        <div className="message-author">
                          <strong>
                            {m.role === "user"
                              ? "You"
                              : m.bot_name || "Assistant"}
                          </strong>
                          <span>
                            {m.role === "assistant"
                              ? "Source-grounded response"
                              : ""}
                          </span>
                        </div>
                        <RichText text={m.content} />
                        {!!m.sources?.length && (
                          <>
                            {sourceCards(m.sources)}
                          </>
                        )}
                        <div className="message-actions">
                          <button
                            title="Copy message"
                            onClick={() => copy(m.content)}
                          >
                            <Copy size={14} />
                          </button>
                          {m.role === "assistant" && (
                            <button
                              title="Regenerate answer"
                              disabled={!!busy}
                              onClick={() =>
                                run("Regenerating answer", async () => {
                                  await api(
                                    `/api/conversations/${chat.id}/messages/${m.id}/regenerate`,
                                    { method: "POST" },
                                  );
                                  const r = await api<{
                                    conversation: Conversation;
                                  }>(`/api/conversations/${chat.id}`);
                                  SC(r.conversation);
                                })
                              }
                            >
                              <RefreshCw size={14} />
                            </button>
                          )}
                        </div>
                      </div>
                    </article>
                  ))}
                </div>
                <div className="composer-area">
                  <div className="assistant-selection">
                    <span>Assistant</span>
                    {bots
                      .filter((b) => b.enabled !== false)
                      .map((b) => (
                        <button
                          className={
                            active.includes(String(b.id)) ? "chosen" : ""
                          }
                          key={b.id}
                          onClick={() =>
                            A((ids) =>
                              ids.includes(String(b.id))
                                ? ids.filter((id) => id !== String(b.id))
                                : [...ids, String(b.id)],
                            )
                          }
                        >
                          <BotIcon size={13} />
                          {b.name}
                          {active.includes(String(b.id)) && <Check size={12} />}
                        </button>
                      ))}
                    {!bots.length && (
                      <button onClick={() => edit()}>
                        Create your first assistant
                        <Plus size={13} />
                      </button>
                    )}
                  </div>
                  <form className="composer" onSubmit={send}>
                    <textarea
                      aria-label="Message your assistant"
                      placeholder={
                        active.length
                          ? "Message this assistant"
                          : bots.length
                            ? "Type your message, then choose an assistant to send"
                            : "Type a message — create an assistant when you are ready to send"
                      }
                      value={message}
                      maxLength={12000}
                      onChange={(e) => SM(e.target.value)}
                      onKeyDown={(e) => {
                        if (
                          e.key === "Enter" &&
                          !e.shiftKey &&
                          !e.nativeEvent.isComposing
                        ) {
                          e.preventDefault();
                          e.currentTarget.form?.requestSubmit();
                        }
                      }}
                    />
                    <div>
                      <span>
                        <ShieldCheck size={13} />
                        {active.length
                          ? "Evidence-backed answers"
                          : bots.length
                            ? "Choose an assistant before sending"
                            : "Create an assistant to send"}
                      </span>
                      <button
                        className="send-button"
                        aria-label="Send message"
                        disabled={!message.trim()}
                      >
                        <ArrowRight size={19} />
                      </button>
                    </div>
                  </form>
                  {queued.length > 0 && (
                    <div className="queue-note" role="status">
                      <Loader2 size={13} className="spin" />
                      {queued.length === 1
                        ? "1 message queued"
                        : `${queued.length} messages queued`}
                    </div>
                  )}
                </div>
              </section>
            </div>
          )}
          {view === "retrieval" && (
            <>
              <Heading title="Retrieval playground" text="" />
              <div className="retrieval-layout">
                <form className="surface retrieval-form" onSubmit={test}>
                  <span className="panel-icon">
                    <FlaskConical size={22} />
                  </span>
                  <h2>Test your knowledge</h2>
                  <p>A good answer begins with relevant context.</p>
                  <label>
                    Question
                    <textarea
                      required
                      minLength={2}
                      maxLength={2000}
                      placeholder="What would your client ask?"
                      value={testQuery}
                      onChange={(e) => TQ(e.target.value)}
                    />
                  </label>
                  <label>
                    Knowledge source
                    <select
                      value={testSource}
                      onChange={(e) => TS(e.target.value)}
                    >
                      <option value="">All knowledge sources</option>
                      {ready.map((f) => (
                        <option key={f.id} value={f.source}>
                          {f.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Number of passages <strong>{topK}</strong>
                    <input
                      type="range"
                      min={1}
                      max={20}
                      value={topK}
                      onChange={(e) => TK(Number(e.target.value))}
                    />
                  </label>
                  <button
                    className="primary"
                    disabled={!!busy || !ready.length}
                  >
                    <Search size={16} />
                    Run retrieval test
                  </button>
                </form>
                <section className="surface retrieval-results">
                  <div className="section-heading">
                    <h2>Retrieved passages</h2>
                    {result && <span className="tag">{result.elapsed} ms</span>}
                  </div>
                  {result ? (
                    result.sources.length ? (
                      result.sources.map((s, i) => (
                        <article className="retrieval-hit" key={i}>
                          <div>
                            <span className="source-number">{i + 1}</span>
                            <strong>{s.source}</strong>
                            <span className="score">
                              Similarity {(s.score || 0).toFixed(3)}
                            </span>
                          </div>
                          <small>{s.location}</small>
                          <p>{s.preview}</p>
                          <button
                            className="text-button"
                            onClick={() =>
                              P({ title: s.source, content: s.preview || "" })
                            }
                          >
                            Inspect passage
                            <ArrowRight size={14} />
                          </button>
                        </article>
                      ))
                    ) : (
                      <Empty
                        icon={<Search />}
                        title="No relevant passages found"
                        text="Try different wording, or add a source that covers this topic."
                      />
                    )
                  ) : (
                    <Empty
                      icon={<Layers />}
                      title="Follow the evidence"
                      text="Run a test to inspect matching passages, their sources, and retrieval scores."
                    />
                  )}
                </section>
              </div>
            </>
          )}
          {view === "settings" && (
            <>
              <Heading
                title="Workspace settings"
                text="Your account, connected services, and workspace information."
              />
              <div className="settings-grid">
                <section className="surface settings-panel">
                  <h2>Your profile</h2>
                  <div className="settings-row">
                    <span>Name</span>
                    <strong>{user?.name}</strong>
                  </div>
                  <div className="settings-row">
                    <span>Email</span>
                    <strong>{user?.email}</strong>
                  </div>
                  <div className="settings-row">
                    <span>Access</span>
                    <span className="tag">Private account</span>
                  </div>
                  <div className="settings-row">
                    <span>Theme</span>
                    <button
                      className="theme-switch"
                      onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
                    >
                      {theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}
                      <span className="nav-text">{theme === "dark" ? "Light mode" : "Dark mode"}</span>
                    </button>
                  </div>
                </section>
                <section className="surface settings-panel">
                  <h2>Connected services</h2>
                  <div className="settings-row">
                    <span>Knowledge storage</span>
                    <strong>{health?.database || "Checking…"}</strong>
                  </div>
                  <div className="settings-row">
                    <span>Retrieval</span>
                    <strong>{health?.retrieval || "Checking…"}</strong>
                  </div>
                  <div className="settings-row">
                    <span>Answer generation</span>
                    <strong>{health?.generation || "Checking…"}</strong>
                  </div>
                  <p className="muted">
                    Service configuration is managed on the server. Secret keys
                    are never shown in this workspace.
                  </p>
                </section>
                <section className="surface settings-panel">
                  <h2>Working with your knowledge</h2>
                  <p>
                    Upload documents, spreadsheets, slides, images, or public
                    web pages. Scanned files are read with OCR. An imported URL
                    includes that page only.
                  </p>
                  <p>
                    Assistants search the files you assign to them. Conversations
                    and citations are saved automatically.
                  </p>
                </section>
              </div>
            </>
          )}
        </div>
      </main>
      {toast && (
        <div className="toast" role="status">
          <Check size={17} />
          {toast}
        </div>
      )}
      {modal && (
        <Dialog
          title={
            modal === "upload"
              ? "Upload document"
              : modal === "bot"
                ? editId
                  ? "Edit assistant"
                  : "Create assistant"
                : "Create assistant"
          }
          onClose={() => !busy && M(null)}
        >
          {modal === "upload" && (
            <>
              <div className="filter-tabs modal-tabs">
                <button
                  className={uploadTab === "file" ? "selected" : ""}
                  onClick={() => UT("file")}
                >
                  <FileText size={16} />
                  Upload files
                </button>
                <button
                  className={uploadTab === "url" ? "selected" : ""}
                  onClick={() => UT("url")}
                >
                  <Globe size={16} />
                  Import web page
                </button>
              </div>
              {uploadTab === "file" ? (
                <>
                  <button
                    className="dropzone"
                    disabled={!!busy}
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={(e) => {
                      e.preventDefault();
                      void upload(Array.from(e.dataTransfer.files));
                    }}
                    onClick={() => input.current?.click()}
                  >
                    <span>
                      <Upload size={28} />
                    </span>
                    <strong>Drop files here, or click to browse</strong>
                    <p>PDF, Word, Excel, PowerPoint, text, and images</p>
                    <small>
                      Up to {health?.max_upload_mb || 25} MB per file · Scanned
                      documents supported
                    </small>
                  </button>
                  <input
                    ref={input}
                    className="visually-hidden"
                    aria-label="Upload documents"
                    type="file"
                    multiple
                    onChange={(e) => {
                      void upload(Array.from(e.target.files || []));
                      e.target.value = "";
                    }}
                  />
                  <div className="upload-info">
                    <ShieldCheck size={18} />
                    <p>Saved privately to this workspace.</p>
                  </div>
                </>
              ) : (
                <form className="stack-form" onSubmit={importUrl}>
                  <label>
                    Web page URL
                    <input
                      required
                      type="url"
                      placeholder="https://example.com/knowledge"
                      value={url}
                      onChange={(e) => SU(e.target.value)}
                    />
                  </label>
                  <button className="primary" disabled={!!busy}>
                    <Globe size={16} />
                    Import page
                  </button>
                </form>
              )}
            </>
          )}
          {modal === "bot" && (
            <form className="stack-form" onSubmit={save}>
              <label>
                Name
                <input
                  required
                  maxLength={100}
                  value={draft.name}
                  placeholder="e.g. Client knowledge bot"
                  onChange={(e) => D({ ...draft, name: e.target.value })}
                />
              </label>
              <label>
                Description
                <input
                  maxLength={500}
                  value={draft.description}
                  placeholder="What should this assistant help with?"
                  onChange={(e) => D({ ...draft, description: e.target.value })}
                />
              </label>
              <label>
                Instructions
                <textarea
                  maxLength={4000}
                  rows={3}
                  value={draft.instructions}
                  onChange={(e) =>
                    D({ ...draft, instructions: e.target.value })
                  }
                />
              </label>
              <div className="source-select-heading">
                <div>
                  <strong>Knowledge sources this assistant can read</strong>
                  <small>
                    {draft.sources.length} of {ready.length} ready files
                    selected
                  </small>
                </div>
                <button
                  type="button"
                  className="text-button"
                  onClick={() =>
                    D({
                      ...draft,
                      sources:
                        draft.sources.length === ready.length
                          ? []
                          : ready.map((f) => f.source),
                    })
                  }
                >
                  {draft.sources.length === ready.length
                    ? "Clear selection"
                    : "Select all"}
                </button>
              </div>
              <div className="source-checklist">
                {ready.map((f) => (
                  <label key={f.id}>
                    <input
                      type="checkbox"
                      checked={draft.sources.includes(f.source)}
                      onChange={(e) =>
                        D({
                          ...draft,
                          sources: e.target.checked
                            ? [...draft.sources, f.source]
                            : draft.sources.filter((s) => s !== f.source),
                        })
                      }
                    />
                    <FileText size={16} />
                    <span>{f.name}</span>
                  </label>
                ))}
                {!ready.length && (
                  <p>Add files to your knowledge base first.</p>
                )}
              </div>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={draft.enabled}
                  onChange={(e) => D({ ...draft, enabled: e.target.checked })}
                />
                Available in chat
              </label>
              <button
                className="primary"
                disabled={!!busy || !draft.name.trim() || !draft.sources.length}
              >
                {editId ? "Save changes" : "Create assistant"}
                <ArrowRight size={16} />
              </button>
            </form>
          )}
          {busy && (
            <p className="dialog-progress" role="status">
              <Loader2 size={16} className="spin" />
              {busy}…
            </p>
          )}
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
        </Dialog>
      )}
      {preview && (
        <Dialog title={preview.title} onClose={() => P(null)} wide>
          <div className="preview-toolbar">
            <span className="tag">Source preview</span>
            <button
              className="text-button"
              onClick={() => copy(preview.content)}
            >
              <Copy size={14} />
              Copy text
            </button>
            {preview.file && preview.file.mime_type !== "text/html" && (
              <a
                className="text-button"
                href={`/api/files/${preview.file.id}/download`}
              >
                <ArrowDownToLine size={14} />
                Download original
              </a>
            )}
          </div>
          <pre className="source-preview">
            {preview.content ||
              "No extracted text is available for this document."}
          </pre>
        </Dialog>
      )}
    </div>
  );
}
function Heading({
  title,
  text,
  action,
}: {
  title: string;
  text: string;
  action?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <h1>{title}</h1>
        {text && <p>{text}</p>}
      </div>
      {action}
    </div>
  );
}
function Empty({
  icon,
  title,
  text,
  action,
}: {
  icon: ReactNode;
  title: string;
  text: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <span className="empty-icon">{icon}</span>
      <h3>{title}</h3>
      <p>{text}</p>
      {action}
    </div>
  );
}
function Status({ value }: { value: string }) {
  return (
    <span className={`status-pill ${value}`}>
      <span />
      {value === "ready"
        ? "Ready"
        : value === "error"
          ? "Needs attention"
          : value === "processing"
            ? "Processing"
            : "Disabled"}
    </span>
  );
}
function Badge({ file }: { file: FileItem }) {
  const web = file.mime_type === "text/html",
    ext = (file.extension || file.name.split(".").pop() || "DOC")
      .replace(".", "")
      .toUpperCase();
  return (
    <span className={`file-badge ${web ? "web" : ext === "PDF" ? "pdf" : ""}`}>
      {web ? <Globe size={21} /> : <FileText size={21} />}
      <small>{web ? "WEB" : ext.slice(0, 4)}</small>
    </span>
  );
}
function RichText({ text }: { text: string }) {
  return (
    <div className="rich-text">
      {text.split("\n").map((line, i) => {
        const parts = line
          .replace(/^#{1,4}\s/, "")
          .split(/(\*\*.*?\*\*)/g)
          .map((p, j) =>
            p.startsWith("**") ? <strong key={j}>{p.slice(2, -2)}</strong> : p,
          );
        return /^#{1,4}\s/.test(line) ? (
          <h3 key={i}>{parts}</h3>
        ) : (
          <p key={i}>{parts}</p>
        );
      })}
    </div>
  );
}
function Dialog({
  title,
  onClose,
  children,
  wide = false,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
  }, []);
  return (
    <dialog
      ref={ref}
      className={`studio-dialog ${wide ? "wide" : ""}`}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
    >
      <div className="dialog-heading">
        <h2>{title}</h2>
        <button aria-label="Close dialog" onClick={onClose}>
          <X size={20} />
        </button>
      </div>
      {children}
    </dialog>
  );
}



