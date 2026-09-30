"use client";

import { ReactNode, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";

type GuardState = "checking" | "allowed";

async function hasSession() {
  const response = await fetch("/api/auth/me", {
    credentials: "include",
    cache: "no-store",
  });
  return response.ok;
}

function AuthLoading() {
  return (
    <main className="auth-shell auth-loading-shell">
      <section className="auth-panel auth-loading-panel">
        <Loader2 className="auth-loading-icon" size={24} aria-hidden="true" />
        <p>Checking your session…</p>
      </section>
    </main>
  );
}

export function ProtectedApp({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [state, setState] = useState<GuardState>("checking");

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        if (await hasSession()) {
          if (active) setState("allowed");
          return;
        }
      } catch {
        // Treat network/auth failures as unauthenticated for route protection.
      }
      if (active) router.replace("/login");
    })();
    return () => {
      active = false;
    };
  }, [router]);

  if (state !== "allowed") return <AuthLoading />;
  return <>{children}</>;
}

export function PublicAuthRoute({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [state, setState] = useState<GuardState>("checking");

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        if (await hasSession()) {
          if (active) router.replace("/");
          return;
        }
      } catch {
        // Logged-out users should be able to see auth routes.
      }
      if (active) setState("allowed");
    })();
    return () => {
      active = false;
    };
  }, [router]);

  if (state !== "allowed") return <AuthLoading />;
  return <>{children}</>;
}