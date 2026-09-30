"use client";

import { ProtectedApp } from "@/components/auth-route";
import { Studio } from "@/components/studio";

export default function Page() {
  return (
    <ProtectedApp>
      <Studio />
    </ProtectedApp>
  );
}