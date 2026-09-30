"use client";

import { PublicAuthRoute } from "@/components/auth-route";
import { ForgotPasswordScreen } from "@/components/auth-screen";

export default function ForgotPasswordPage() {
  return (
    <PublicAuthRoute>
      <ForgotPasswordScreen />
    </PublicAuthRoute>
  );
}