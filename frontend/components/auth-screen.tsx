"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  ArrowRight,
  BrainCircuit,
  Eye,
  EyeOff,
  KeyRound,
  Lock,
  Mail,
  ShieldCheck,
  UserRound,
} from "lucide-react";
import { api, jsonBody } from "@/lib/api";

type AuthMode = "login" | "signup";
type ResetStep = "email" | "code" | "password" | "done";

function passwordScore(password: string) {
  let score = 0;
  if (password.length >= 12) score++;
  if (/[a-z]/.test(password) && /[A-Z]/.test(password)) score++;
  if (/\d/.test(password)) score++;
  if (/[^A-Za-z0-9]/.test(password)) score++;
  return score;
}

function maskEmail(email: string) {
  const [name, domain] = email.split("@");
  if (!name || !domain) return email;
  return `${name[0]}${"*".repeat(Math.max(2, name.length - 1))}@${domain}`;
}

function PasswordInput({
  value,
  onChange,
  placeholder = "Enter password",
  autoComplete,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  autoComplete?: string;
}) {
  const [show, setShow] = useState(false);
  return (
    <div className="input-wrap">
      <Lock size={18} />
      <input
        required
        type={show ? "text" : "password"}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        autoComplete={autoComplete}
      />
      <button
        type="button"
        className="input-icon-button"
        aria-label={show ? "Hide password" : "Show password"}
        onClick={() => setShow((value) => !value)}
      >
        {show ? <EyeOff size={17} /> : <Eye size={17} />}
      </button>
    </div>
  );
}

function AuthFrame({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    const saved = window.localStorage.getItem("synapse-theme") as "light" | "dark" | null;
    const preferred = window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    document.documentElement.dataset.theme = saved || preferred;
  }, []);
  return (
    <main className="auth-shell">
      <section className="auth-art" aria-hidden="true">
        <div className="auth-neural" />
      </section>
      <section className="auth-panel">{children}</section>
    </main>
  );
}

function GoogleIcon() {
  return (
    <svg className="google-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
      <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.15v2.84C3.96 20.53 7.67 23 12 23z" />
      <path fill="#FBBC05" d="M5.84 14.1c-.22-.66-.35-1.36-.35-2.1s.13-1.44.35-2.1V7.06H2.15C1.41 8.53 1 10.22 1 12s.41 3.47 1.15 4.94l3.69-2.84z" />
      <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.67 1 3.96 3.47 2.15 7.06l3.69 2.84C6.71 7.3 9.14 5.38 12 5.38z" />
    </svg>
  );
}
function Brand() {
  return (
    <Link className="brand-link" href="/" aria-label="Synapse home">
      <span><BrainCircuit size={24} /></span>
      <strong>Synapse</strong>
    </Link>
  );
}

export function AuthScreen({ mode }: { mode: AuthMode }) {
  const router = useRouter();
  const search = useSearchParams();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const authError = search.get("error");
  const initialMessage = search.get("verified")
    ? "Email verified. You can sign in now."
    : authError === "google_unavailable"
      ? "Google sign-in is not configured yet."
      : authError
        ? "Google sign-in could not be completed."
        : "";
  const [message, setMessage] = useState(initialMessage);
  const [busy, setBusy] = useState(false);
  const isSignup = mode === "signup";
  const score = passwordScore(password);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setMessage("");
    if (isSignup) {
      if (password.length < 12) return setMessage("Password must be at least 12 characters.");
      if (score < 3) return setMessage("Use uppercase, lowercase, and a number. Symbols are recommended.");
      if (password !== confirmPassword) return setMessage("Passwords do not match.");
    }
    setBusy(true);
    try {
      const result = await api<{
        ok: boolean;
        email?: string;
        purpose?: string;
        dev_code?: string;
        message?: string;
        user?: unknown;
      }>(isSignup ? "/api/auth/signup" : "/api/auth/login", {
        method: "POST",
        body: jsonBody(isSignup ? { name, email, password } : { email, password }),
      });
      if (isSignup || result.purpose) {
        if (result.dev_code) sessionStorage.setItem("synapse-dev-code", result.dev_code);
        const params = new URLSearchParams({ email: result.email || email, purpose: result.purpose || "signup" });
        router.push(`/verify?${params.toString()}`);
        return;
      }
      router.push("/");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "We couldn't complete your request. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  function google() {
    window.location.href = "/api/auth/google/start";
  }

  return (
    <AuthFrame>
      <Brand />
      <div className="auth-copy">
        <p className="eyebrow">Private document intelligence</p>
        <h1>{isSignup ? "Create your account" : "Welcome back"}</h1>
        <p>{isSignup ? "Create a secure Synapse account for your private document workspace." : "Sign in to continue to Synapse."}</p>
      </div>
      {!isSignup ? (
        <>
          <button type="button" className="google-button" onClick={google} disabled={busy}>
            <span className="google-mark"><GoogleIcon /></span>
            Continue with Google
          </button>
          <div className="auth-divider"><span>OR</span></div>
        </>
      ) : null}
      <form className="auth-form" onSubmit={submit}>
        {isSignup ? (
          <label>
            <span>Full name</span>
            <div className="input-wrap">
              <UserRound size={18} />
              <input required value={name} onChange={(event) => setName(event.target.value)} placeholder="Irtiza Rashid" autoComplete="name" />
            </div>
          </label>
        ) : null}
        <label>
          <span>Email</span>
          <div className="input-wrap">
            <Mail size={18} />
            <input required type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@example.com" autoComplete="email" />
          </div>
        </label>
        <label>
          <span className="password-label-row">
            <span>Password</span>
            {!isSignup ? <Link className="forgot-link" href="/forgot-password">Forgot password?</Link> : null}
          </span>
          <PasswordInput value={password} onChange={setPassword} autoComplete={isSignup ? "new-password" : "current-password"} />
        </label>
        {isSignup ? (
          <>
            <label>
              <span>Confirm password</span>
              <PasswordInput value={confirmPassword} onChange={setConfirmPassword} placeholder="Confirm password" autoComplete="new-password" />
            </label>
            <div className="password-meter" aria-label="Password strength">
              <span data-on={score >= 1} />
              <span data-on={score >= 2} />
              <span data-on={score >= 3} />
              <span data-on={score >= 4} />
            </div>
            <p className="form-note">Use at least 12 characters with uppercase, lowercase, and a number. Symbols and password managers are supported.</p>
          </>
        ) : null}
        {message ? <p className={message.includes("verified") ? "form-note" : "form-error"}>{message}</p> : null}
        <button className="action-button" disabled={busy}>
          <span>{busy ? (isSignup ? "Creating account..." : "Signing in...") : isSignup ? "Create account" : "Sign in"}</span>
          <ArrowRight size={18} />
        </button>
      </form>
      {isSignup ? (
        <>
          <div className="auth-divider"><span>OR</span></div>
          <button type="button" className="google-button" onClick={google} disabled={busy}>
            <span className="google-mark"><GoogleIcon /></span>
            Continue with Google
          </button>
        </>
      ) : null}
      <p className="auth-switch">
        {isSignup ? "Already have an account?" : "Don't have an account?"}{" "}
        <Link href={isSignup ? "/login" : "/signup"}>{isSignup ? "Sign in" : "Sign up"}</Link>
      </p>
    </AuthFrame>
  );
}

export function VerifyScreen() {
  const router = useRouter();
  const params = useSearchParams();
  const initialEmail = params.get("email") || "";
  const initialPurpose = params.get("purpose") || "signup";
  const initialCode = typeof window !== "undefined" ? sessionStorage.getItem("synapse-dev-code") || "" : "";
  const [email, setEmail] = useState(initialEmail);
  const [purpose] = useState(initialPurpose);
  const [code, setCode] = useState(initialCode);
  const [message, setMessage] = useState(initialCode ? `Development code filled: ${initialCode}` : "");
  const [busy, setBusy] = useState(false);
  const [seconds, setSeconds] = useState(180);
  const [cooldown, setCooldown] = useState(0);

  useEffect(() => {
    if (seconds <= 0) return;
    const id = window.setInterval(() => setSeconds((value) => Math.max(0, value - 1)), 1000);
    return () => window.clearInterval(id);
  }, [seconds]);
  useEffect(() => {
    if (cooldown <= 0) return;
    const id = window.setInterval(() => setCooldown((value) => Math.max(0, value - 1)), 1000);
    return () => window.clearInterval(id);
  }, [cooldown]);

  const title = useMemo(() => (purpose === "signup" ? "Verify your account" : "Enter your login code"), [purpose]);
  const mm = String(Math.floor(seconds / 60)).padStart(2, "0");
  const ss = String(seconds % 60).padStart(2, "0");

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (seconds <= 0) return setMessage("This code has expired. Request a new code.");
    setBusy(true);
    setMessage("");
    try {
      const result = await api<{ redirect?: string }>("/api/auth/otp/verify", { method: "POST", body: jsonBody({ email, code, purpose }) });
      router.push(result.redirect === "/login?verified=1" ? "/login?verified=1" : "/");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Code could not be verified.");
    } finally {
      setBusy(false);
    }
  }

  async function resend() {
    setBusy(true);
    setMessage("");
    try {
      const result = await api<{ dev_code?: string; message?: string }>("/api/auth/otp/request", { method: "POST", body: jsonBody({ email, purpose }) });
      if (result.dev_code) {
        sessionStorage.setItem("synapse-dev-code", result.dev_code);
        setCode(result.dev_code);
      }
      setSeconds(180);
      setCooldown(30);
      setMessage(result.dev_code ? `Development code filled: ${result.dev_code}` : result.message || "Code sent.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not send a new code.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-shell verify-shell">
      <section className="auth-panel compact">
        <Brand />
        <div className="auth-copy">
          <p className="eyebrow">Check your email</p>
          <h1>{title}</h1>
          <p>We sent a 6-digit verification code to {email ? maskEmail(email) : "your email"}.</p>
        </div>
        <form className="auth-form" onSubmit={submit}>
          <label>
            <span>Email</span>
            <div className="input-wrap"><Mail size={18} /><input required type="email" value={email} onChange={(event) => setEmail(event.target.value)} /></div>
          </label>
          <label>
            <span>Verification code</span>
            <div className="input-wrap otp-wrap"><KeyRound size={18} /><input required inputMode="numeric" pattern="[0-9]*" maxLength={6} value={code} onChange={(event) => setCode(event.target.value.replace(/\D/g, "").slice(0, 6))} placeholder="000000" /></div>
          </label>
          <p className={seconds ? "form-note" : "form-error"}>{seconds ? `Code expires in ${mm}:${ss}` : "This code has expired."}</p>
          {message ? <p className={message.includes("could") || message.includes("expired") || message.includes("incorrect") || message.includes("Too many") ? "form-error" : "form-note"}>{message}</p> : null}
          <button className="action-button" disabled={busy || !email || code.length < 4 || seconds <= 0}><span>{busy ? "Verifying..." : "Verify code"}</span><ArrowRight size={18} /></button>
          <button className="ghost-button" type="button" disabled={busy || !email || cooldown > 0} onClick={resend}>{cooldown ? `Resend code in ${cooldown}s` : "Request new code"}</button>
        </form>
      </section>
    </main>
  );
}

export function ForgotPasswordScreen() {
  const [step, setStep] = useState<ResetStep>("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [resetToken, setResetToken] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [seconds, setSeconds] = useState(180);
  const [cooldown, setCooldown] = useState(0);
  const score = passwordScore(password);

  useEffect(() => {
    if (step !== "code" || seconds <= 0) return;
    const id = window.setInterval(() => setSeconds((value) => Math.max(0, value - 1)), 1000);
    return () => window.clearInterval(id);
  }, [step, seconds]);
  useEffect(() => {
    if (cooldown <= 0) return;
    const id = window.setInterval(() => setCooldown((value) => Math.max(0, value - 1)), 1000);
    return () => window.clearInterval(id);
  }, [cooldown]);

  async function requestCode(event?: FormEvent) {
    event?.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      const result = await api<{ message?: string; dev_code?: string }>("/api/auth/password/forgot", { method: "POST", body: jsonBody({ email }) });
      if (result.dev_code) setCode(result.dev_code);
      setSeconds(180);
      setCooldown(30);
      setStep("code");
      setMessage(result.message || "If an account exists for this email, we've sent a password reset code.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "We couldn't send a code. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  async function verifyCode(event: FormEvent) {
    event.preventDefault();
    if (seconds <= 0) return setMessage("This code has expired. Request a new code.");
    setBusy(true);
    setMessage("");
    try {
      const result = await api<{ reset_token: string }>("/api/auth/password/reset/verify", { method: "POST", body: jsonBody({ email, code }) });
      setResetToken(result.reset_token);
      setStep("password");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Incorrect verification code.");
    } finally {
      setBusy(false);
    }
  }

  async function resetPassword(event: FormEvent) {
    event.preventDefault();
    setMessage("");
    if (password.length < 12) return setMessage("Password must be at least 12 characters.");
    if (score < 3) return setMessage("Use uppercase, lowercase, and a number. Symbols are recommended.");
    if (password !== confirmPassword) return setMessage("Passwords do not match.");
    setBusy(true);
    try {
      const result = await api<{ message?: string }>("/api/auth/password/reset", { method: "POST", body: jsonBody({ reset_token: resetToken, password }) });
      setMessage(result.message || "Your password has been changed successfully.");
      setStep("done");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "We couldn't reset your password. Please request a new code.");
    } finally {
      setBusy(false);
    }
  }

  const mm = String(Math.floor(seconds / 60)).padStart(2, "0");
  const ss = String(seconds % 60).padStart(2, "0");

  return (
    <AuthFrame>
      <Brand />
      <div className="auth-copy">
        <p className="eyebrow">Account recovery</p>
        <h1>{step === "email" ? "Reset your password" : step === "code" ? "Check your email" : step === "password" ? "Create a new password" : "Password updated"}</h1>
        <p>{step === "email" ? "Enter the email associated with your account." : step === "code" ? `We sent a 6-digit verification code to ${maskEmail(email)}.` : step === "password" ? "Choose a new password. Other active sessions will be revoked." : "Your password has been changed successfully."}</p>
      </div>
      {step === "email" ? (
        <form className="auth-form" onSubmit={requestCode}>
          <label><span>Email</span><div className="input-wrap"><Mail size={18} /><input required type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" autoComplete="email" /></div></label>
          {message ? <p className="form-note">{message}</p> : null}
          <button className="action-button" disabled={busy}><span>{busy ? "Sending code..." : "Send reset code"}</span><ArrowRight size={18} /></button>
        </form>
      ) : null}
      {step === "code" ? (
        <form className="auth-form" onSubmit={verifyCode}>
          <label><span>Verification code</span><div className="input-wrap otp-wrap"><KeyRound size={18} /><input required inputMode="numeric" pattern="[0-9]*" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))} placeholder="000000" /></div></label>
          <p className={seconds ? "form-note" : "form-error"}>{seconds ? `Code expires in ${mm}:${ss}` : "This code has expired."}</p>
          {message ? <p className={message.includes("incorrect") || message.includes("expired") || message.includes("Too many") ? "form-error" : "form-note"}>{message}</p> : null}
          <button className="action-button" disabled={busy || code.length < 4 || seconds <= 0}><span>{busy ? "Verifying..." : "Verify code"}</span><ArrowRight size={18} /></button>
          <button className="ghost-button" type="button" disabled={busy || cooldown > 0} onClick={() => requestCode()}>{cooldown ? `Resend code in ${cooldown}s` : "Request new code"}</button>
        </form>
      ) : null}
      {step === "password" ? (
        <form className="auth-form" onSubmit={resetPassword}>
          <label><span>New password</span><PasswordInput value={password} onChange={setPassword} autoComplete="new-password" /></label>
          <label><span>Confirm new password</span><PasswordInput value={confirmPassword} onChange={setConfirmPassword} placeholder="Confirm new password" autoComplete="new-password" /></label>
          <div className="password-meter" aria-label="Password strength"><span data-on={score >= 1} /><span data-on={score >= 2} /><span data-on={score >= 3} /><span data-on={score >= 4} /></div>
          <p className="form-note">Use at least 12 characters with uppercase, lowercase, and a number.</p>
          {message ? <p className="form-error">{message}</p> : null}
          <button className="action-button" disabled={busy}><span>{busy ? "Resetting password..." : "Reset password"}</span><ArrowRight size={18} /></button>
        </form>
      ) : null}
      {step === "done" ? (
        <div className="auth-form"><p className="form-note"><ShieldCheck size={16} /> {message}</p><Link className="action-button" href="/login"><span>Back to sign in</span><ArrowRight size={18} /></Link></div>
      ) : null}
      <p className="auth-switch"><Link href="/login">Back to sign in</Link></p>
    </AuthFrame>
  );
}

