export type User = { id: number; name: string; email: string };

export type FileItem = {
  id: string;
  source: string;
  name: string;
  extension?: string;
  mime_type?: string;
  size_bytes?: number;
  status?: "ready" | "processing" | "error" | string;
  chunks?: number;
  created_at?: number;
  updated_at?: number;
  bots?: string[];
};

export type Bot = {
  id: string | number;
  name: string;
  description?: string;
  instructions?: string;
  sources: string[];
  enabled?: boolean;
  avatar?: string;
  color?: string;
};

export type ConversationMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  bot_id?: string;
  bot_name?: string;
  attachments?: string[];
  sources?: SourceHit[];
  created_at?: number;
};

export type Conversation = {
  id: string;
  title: string;
  bot_ids: string[];
  messages?: ConversationMessage[];
  created_at?: number;
  updated_at?: number;
};

export type SourceHit = {
  number?: number;
  source: string;
  location?: string;
  score?: number;
  preview?: string;
};

export type BotPayload = {
  name: string;
  description: string;
  instructions: string;
  enabled: boolean;
  avatar: string;
  color: string;
  sources: string[];
};

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const isFormData = init.body instanceof FormData;
  if (init.body && !isFormData && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, {
    ...init,
    headers,
    credentials: "include",
  });
  if (
    response.status === 401 &&
    typeof window !== "undefined" &&
    !window.location.pathname.startsWith("/login")
  ) {
    window.location.href = "/login";
  }
  const text = await response.text();
  let data;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    throw new ApiError(
      "The server is unavailable. Please try again shortly.",
      response.status,
    );
  }
  if (!response.ok) {
    const detail = data.detail;
    throw new ApiError(
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((item: { msg?: string }) => item.msg).join(". ")
          : data.message || "Request failed",
      response.status,
    );
  }
  return data as T;
}

export function jsonBody(value: unknown) {
  return JSON.stringify(value);
}

export function formatBytes(value?: number) {
  if (!value) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let amount = value;
  let unit = 0;
  while (amount >= 1024 && unit < units.length - 1) {
    amount /= 1024;
    unit += 1;
  }
  return `${amount >= 10 || unit === 0 ? amount.toFixed(0) : amount.toFixed(1)} ${units[unit]}`;
}

export function formatDate(value?: number) {
  if (!value) return "Recently";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
  }).format(new Date(value * 1000));
}

export function fileExtension(file: Pick<FileItem, "extension" | "name">) {
  return (file.extension || file.name?.split(".").pop() || "doc")
    .replace(".", "")
    .slice(0, 4)
    .toUpperCase();
}

export const botAvatars = ["A", "Q", "R", "N", "S", "V", "K", "M"];
export const botColors = [
  "#6f62ff",
  "#10a38f",
  "#e05c7d",
  "#b7791f",
  "#1677ff",
  "#8b5cf6",
  "#0f766e",
];
