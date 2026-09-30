"use client";

import { Suspense } from "react";
import { PublicAuthRoute } from "@/components/auth-route";
import { VerifyScreen } from "@/components/auth-screen";

export default function VerifyPage() {
  return (
    <Suspense fallback={null}>
      <PublicAuthRoute>
        <VerifyScreen />
      </PublicAuthRoute>
    </Suspense>
  );
}
