/**
 * MirrorSelf API client. Talks to the FastAPI backend.
 *
 * On the client we hit `/api/*` and a Next.js route handler proxies to the
 * backend. On the server (route handlers, RSC) we hit the backend directly
 * via `process.env.API_INTERNAL_URL`.
 */
import axios, { AxiosInstance } from "axios";

// On the browser we call /api/<path>, where the catch-all route handler in
// src/app/api/[...path]/route.ts forwards to the FastAPI backend. On the
// server (route handlers, RSC) we hit the backend directly.
const BROWSER_BASE = "/api";
const SERVER_BASE = process.env.API_INTERNAL_URL || "http://localhost:8000";

const isBrowser = typeof window !== "undefined";

function client(token?: string): AxiosInstance {
  // Path is expected to be "/v1/..." so the v1 prefix is preserved.
  const baseURL = isBrowser ? BROWSER_BASE : SERVER_BASE;
  const instance = axios.create({
    baseURL,
    timeout: 60_000,
    headers: { "Content-Type": "application/json" },
  });
  if (token) instance.defaults.headers.common.Authorization = `Bearer ${token}`;
  return instance;
}

// --- Types ----------------------------------------------------------------

export type PersonalityProfile = {
  values: string[];
  communication_style?: string | null;
  humor?: string | null;
  fears: string[];
  dreams: string[];
};

export type UserPrivate = {
  id: number;
  email: string;
  username: string;
  display_name?: string | null;
  bio?: string | null;
  is_public: boolean;
  is_onboarded: boolean;
  twin_status: "pending" | "processing" | "ready" | "failed";
  avatar_video_path?: string | null;
  voice_id?: string | null;
  face_photo_path?: string | null;
  personality?: PersonalityProfile | null;
  conversation_count: number;
  created_at: string;
};

export type UserPublic = Omit<UserPrivate, "email" | "personality" | "conversation_count" | "voice_id" | "face_photo_path">;

export type MessageOut = {
  id: number;
  role: "user" | "assistant";
  content: string;
  detected_emotion?: string | null;
  response_tone?: string | null;
  audio_url?: string | null;
  video_url?: string | null;
  created_at: string;
};

export type ChatResponse = {
  conversation_id: number;
  user_message: MessageOut;
  assistant_message: MessageOut;
  new_facts: string[];
};

export type ConversationSummary = {
  id: number;
  title?: string | null;
  created_at: string;
  updated_at: string;
  message_count: number;
};

// --- Auth -----------------------------------------------------------------

export async function register(payload: { email: string; username: string; password: string; display_name?: string }) {
  const { data } = await client().post("/v1/auth/register", payload);
  return data as { access_token: string; user: UserPrivate };
}

export async function login(payload: { email: string; password: string }) {
  const { data } = await client().post("/v1/auth/login", payload);
  return data as { access_token: string; user: UserPrivate };
}

export async function me(token: string) {
  const { data } = await client(token).get("/v1/auth/me");
  return data as UserPrivate;
}

// --- Onboarding -----------------------------------------------------------

export async function uploadFace(token: string, file: File) {
  const form = new FormData();
  form.append("photo", file);
  const { data } = await client(token).post("/v1/onboarding/face", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data as UserPrivate;
}

export async function uploadVoice(token: string, file: File) {
  const form = new FormData();
  form.append("audio", file);
  const { data } = await client(token).post("/v1/onboarding/voice", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data as UserPrivate;
}

export async function submitQuiz(token: string, personality: PersonalityProfile) {
  const { data } = await client(token).post("/v1/onboarding/quiz", personality);
  return data as UserPrivate;
}

export async function generateAvatar(token: string) {
  const { data } = await client(token).post("/v1/onboarding/generate-avatar");
  return data as UserPrivate;
}

// --- Chat -----------------------------------------------------------------

export async function chat(token: string, message: string, conversation_id?: number) {
  const { data } = await client(token).post("/v1/chat", { message, conversation_id });
  return data as ChatResponse;
}

// --- Public profile -------------------------------------------------------

export async function getPublicProfile(username: string) {
  const { data } = await client().get(`/v1/u/${username}`);
  return data as UserPublic;
}

export async function chatWithPublicTwin(username: string, message: string, token?: string) {
  const { data } = await client(token).post(`/v1/u/${username}/chat`, { message });
  return data as ChatResponse;
}

// --- Me -------------------------------------------------------------------

export async function updateMe(token: string, patch: Partial<Pick<UserPrivate, "display_name" | "bio" | "is_public" | "personality">>) {
  const { data } = await client(token).patch("/v1/me", patch);
  return data as UserPrivate;
}

export async function listConversations(token: string) {
  const { data } = await client(token).get("/v1/me/conversations");
  return data as ConversationSummary[];
}
