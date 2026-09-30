"use client";

import { Suspense } from "react";
import { PublicAuthRoute } from "@/components/auth-route";
import { AuthScreen } from "@/components/auth-screen";

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <PublicAuthRoute>
        <AuthScreen mode="login" />
      </PublicAuthRoute>
    </Suspense>
  );
}