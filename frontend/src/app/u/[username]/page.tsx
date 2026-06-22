"use client";
import { useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { toast } from "sonner";
import { Send, Loader2, Volume2, Sparkles, MessageCircle } from "lucide-react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getPublicProfile, chatWithPublicTwin } from "@/lib/api";
import type { UserPublic, ChatResponse, MessageOut } from "@/lib/api";
import { useAuth } from "@/lib/auth-store";
import { cn } from "@/lib/utils";

export default function PublicTwinPage() {
  const params = useParams<{ username: string }>();
  const router = useRouter();
  const { token } = useAuth();
  const username = params.username;

  const [profile, setProfile] = useState<UserPublic | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [messages, setMessages] = useState<MessageOut[]>([]);
  const [conversationId, setConversationId] = useState<number | null>(null);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const audioRef = useRef<HTMLAudioElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!username) return;
    (async () => {
      try {
        const p = await getPublicProfile(username);
        setProfile(p);
      } catch (e: any) {
        if (e?.response?.status === 404) setNotFound(true);
        else toast.error("Could not load profile");
      }
    })();
  }, [username]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, sending]);

  async function send() {
    const text = input.trim();
    if (!text || sending || !username) return;
    setInput("");
    setSending(true);
    try {
      const res: ChatResponse = await chatWithPublicTwin(username, text, token ?? undefined);
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
      console.warn("Play failed", e);
    } finally {
      setSpeaking(false);
    }
  }

  if (notFound) {
    return (
      <main className="min-h-screen grid place-items-center p-6">
        <Card className="max-w-md w-full">
          <CardHeader>
            <CardTitle>Twin not found</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              @{username} doesn&rsquo;t exist, or hasn&rsquo;t made their twin public yet.
            </p>
            <Button className="mt-4" onClick={() => router.push("/")}>Go home</Button>
          </CardContent>
        </Card>
      </main>
    );
  }

  if (!profile) {
    return (
      <main className="min-h-screen grid place-items-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </main>
    );
  }

  return (
    <main className="min-h-screen flex flex-col">
      <header className="border-b px-6 py-4">
        <div className="container max-w-3xl flex items-center gap-3">
          <Avatar className="h-12 w-12">
            <AvatarImage src={profile.avatar_video_path ? undefined : undefined} />
            <AvatarFallback>{profile.display_name?.[0] ?? profile.username[0]}</AvatarFallback>
          </Avatar>
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <h1 className="font-semibold">{profile.display_name ?? profile.username}</h1>
              <span className="text-xs text-muted-foreground">@{profile.username}</span>
            </div>
            {profile.bio && <p className="text-sm text-muted-foreground mt-0.5">{profile.bio}</p>}
          </div>
          <div className="flex items-center gap-1 text-xs text-muted-foreground">
            <Sparkles className="h-3 w-3" /> AI twin
          </div>
        </div>
      </header>

      <div className="flex-1 container max-w-3xl py-6 grid grid-rows-[1fr_auto] gap-4">
        <div ref={scrollRef} className="overflow-y-auto pr-2 space-y-4">
          {messages.length === 0 && (
            <div className="text-center text-muted-foreground mt-12">
              <MessageCircle className="h-8 w-8 mx-auto mb-2" />
              <p>You&rsquo;re talking to {profile.display_name ?? profile.username}&rsquo;s digital twin.</p>
              <p className="text-sm mt-1">It will respond in their voice and tone.</p>
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
            placeholder={`Say something to ${profile.display_name ?? profile.username}…`}
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
