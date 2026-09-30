"use client";

import { Suspense } from "react";
import { PublicAuthRoute } from "@/components/auth-route";
import { AuthScreen } from "@/components/auth-screen";

export default function SignupPage() {
  return (
    <Suspense fallback={null}>
      <PublicAuthRoute>
        <AuthScreen mode="signup" />
      </PublicAuthRoute>
    </Suspense>
  );
}