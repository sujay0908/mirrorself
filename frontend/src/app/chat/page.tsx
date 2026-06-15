"use client";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Mic, Send, Loader2, Volume2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/lib/auth-store";
import { chat } from "@/lib/api";
import type { ChatResponse, MessageOut } from "@/lib/api";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { cn } from "@/lib/utils";

export default function ChatPage() {
  const router = useRouter();
  const { token, user } = useAuth();
  const [conversationId, setConversationId] = useState<number | null>(null);
  const [messages, setMessages] = useState<MessageOut[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const audioRef = useRef<HTMLAudioElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!token) router.push("/login");
  }, [token, router]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, sending]);

  async function send() {
    const text = input.trim();
    if (!text || !token || sending) return;
    setInput("");
    setSending(true);
    try {
      const res: ChatResponse = await chat(token, text, conversationId ?? undefined);
      setConversationId(res.conversation_id);
      setMessages((m) => [...m, res.user_message, res.assistant_message]);
      await playAssistant(res.assistant_message);
    } catch (err: any) {
      toast.error(err?.response?.data?.detail ?? "Chat failed");
    } finally {
      setSending(false);
    }
  }

  async function playAssistant(msg: MessageOut) {
    const url = msg.audio_url || msg.video_url;
    if (!url) return;
    setSpeaking(true);
    const el = msg.video_url ? videoRef.current : audioRef.current;
    if (!el) {
      setSpeaking(false);
      return;
    }
    el.src = url;
    try {
      await el.play();
      await new Promise<void>((resolve) => {
        el.onended = () => resolve();
        el.onerror = () => resolve();
      });
    } catch (e) {
      console.warn("Audio play failed", e);
    } finally {
      setSpeaking(false);
    }
  }

  if (!token || !user) return null;

  return (
    <main className="min-h-screen flex flex-col">
      <header className="border-b px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-2 font-semibold">
          <Avatar className="h-7 w-7">
            <AvatarImage src={user.face_photo_path || undefined} />
            <AvatarFallback>{user.display_name?.[0] ?? user.username[0]}</AvatarFallback>
          </Avatar>
          Talking to {user.display_name ?? user.username}'s twin
        </div>
        <Button variant="outline" size="sm" onClick={() => router.push("/settings")}>
          Settings
        </Button>
      </header>

      <div className="flex-1 container max-w-3xl py-6 grid grid-rows-[1fr_auto] gap-4">
        <div ref={scrollRef} className="overflow-y-auto pr-2 space-y-4">
          {messages.length === 0 && (
            <div className="text-center text-muted-foreground mt-20">
              <p className="text-lg">Say hello to your twin.</p>
              <p className="text-sm mt-2">It already knows your personality, voice, and face.</p>
            </div>
          )}
          {messages.map((m) => (
            <div key={m.id} className={cn("flex", m.role === "user" ? "justify-end" : "justify-start")}>
              <div
                className={cn(
                  "rounded-2xl px-4 py-2 max-w-[80%] text-sm",
                  m.role === "user" ? "bg-primary text-primary-foreground" : "bg-muted"
                )}
              >
                {m.content}
                {m.response_tone && (
                  <span className="ml-2 text-[10px] uppercase tracking-wide opacity-60">
                    {m.response_tone}
                  </span>
                )}
              </div>
            </div>
          ))}
          {sending && (
            <div className="flex justify-start">
              <div className="rounded-2xl px-4 py-2 bg-muted text-sm flex items-center gap-2">
                <Loader2 className="h-3 w-3 animate-spin" /> thinking…
              </div>
            </div>
          )}
        </div>

        <div className="flex items-end gap-2 border-t pt-4">
          <Textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Type or hold the mic to talk…"
            rows={1}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            className="resize-none"
          />
          <Button onClick={send} disabled={sending || !input.trim()} size="icon">
            <Send className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <div className="sr-only">
        <audio ref={audioRef} />
        <video ref={videoRef} playsInline />
      </div>

      {speaking && (
        <div className="fixed bottom-24 right-6 flex items-center gap-2 rounded-full bg-primary text-primary-foreground px-4 py-2 shadow-lg speaking">
          <Volume2 className="h-4 w-4" /> speaking
        </div>
      )}
    </main>
  );
}
