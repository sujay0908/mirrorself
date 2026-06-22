"use client";
import { useRef, useState } from "react";
import { toast } from "sonner";
import { Mic, Square, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { uploadVoice } from "@/lib/api";
import type { UserPrivate } from "@/lib/api";

export function StepVoice({ token, user, onDone }: { token: string; user: UserPrivate; onDone: (u: UserPrivate) => void }) {
  const [recording, setRecording] = useState(false);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null);
  const [seconds, setSeconds] = useState(0);
  const [loading, setLoading] = useState(false);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function startRecording() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rec = new MediaRecorder(stream);
      chunksRef.current = [];
      rec.ondataavailable = (e) => e.data.size && chunksRef.current.push(e.data);
      rec.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        setAudioBlob(blob);
        setAudioUrl(URL.createObjectURL(blob));
        stream.getTracks().forEach((t) => t.stop());
      };
      rec.start();
      recorderRef.current = rec;
      setRecording(true);
      setSeconds(0);
      timerRef.current = setInterval(() => setSeconds((s) => s + 1), 1000);
    } catch (e) {
      toast.error("Microphone permission denied");
    }
  }

  function stopRecording() {
    recorderRef.current?.stop();
    setRecording(false);
    if (timerRef.current) clearInterval(timerRef.current);
  }

  async function upload(blob: Blob) {
    setLoading(true);
    try {
      const file = new File([blob], "voice-sample.webm", { type: blob.type });
      const updated = await uploadVoice(token, file);
      onDone(updated);
    } catch (err: any) {
      toast.error(err?.response?.data?.detail ?? "Upload failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold">Record 30 seconds of your voice</h2>
        <p className="text-sm text-muted-foreground">
          Read anything out loud. We&rsquo;ll use it to clone your voice. Minimum 6 seconds, max 2 minutes.
        </p>
      </div>

      <div className="grid place-items-center gap-3">
        <div className="text-4xl font-mono tabular-nums">
          {String(Math.floor(seconds / 60)).padStart(2, "0")}:{String(seconds % 60).padStart(2, "0")}
        </div>

        {!recording ? (
          <Button onClick={startRecording} size="lg" disabled={loading} className="rounded-full h-16 w-16 p-0">
            <Mic className="h-6 w-6" />
          </Button>
        ) : (
          <Button onClick={stopRecording} size="lg" variant="destructive" className="rounded-full h-16 w-16 p-0">
            <Square className="h-6 w-6" />
          </Button>
        )}

        {audioUrl && <audio src={audioUrl} controls className="w-full" />}

        <div className="flex gap-2 w-full">
          <Button variant="outline" onClick={() => fileInputRef.current?.click()} className="flex-1">
            <Upload className="h-4 w-4 mr-2" /> Or upload file
          </Button>
          <Button onClick={() => audioBlob && upload(audioBlob)} disabled={!audioBlob || loading} className="flex-1">
            Continue
          </Button>
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept="audio/*"
          className="hidden"
          onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])}
        />
      </div>
    </div>
  );
}
