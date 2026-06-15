"use client";
import { useRef, useState } from "react";
import { toast } from "sonner";
import { Camera, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { uploadFace } from "@/lib/api";
import type { UserPrivate } from "@/lib/api";

export function StepFace({ token, user, onDone }: { token: string; user: UserPrivate; onDone: (u: UserPrivate) => void }) {
  const [preview, setPreview] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  async function onPick(file: File) {
    setPreview(URL.createObjectURL(file));
    setLoading(true);
    try {
      const updated = await uploadFace(token, file);
      onDone(updated);
    } catch (err: any) {
      toast.error(err?.response?.data?.detail ?? "Upload failed");
      setPreview(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold">Upload a face photo</h2>
        <p className="text-sm text-muted-foreground">
          A clear, front-facing photo with good lighting. We'll use it to generate a talking head.
        </p>
      </div>

      <div className="grid place-items-center">
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={loading}
          className="relative aspect-square w-48 rounded-full border-2 border-dashed border-muted-foreground/40 flex items-center justify-center overflow-hidden hover:border-primary transition-colors"
        >
          {preview ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={preview} alt="Face preview" className="h-full w-full object-cover" />
          ) : (
            <Camera className="h-8 w-8 text-muted-foreground" />
          )}
          {loading && <div className="absolute inset-0 grid place-items-center bg-background/70"><Loader2 className="h-6 w-6 animate-spin" /></div>}
        </button>
        <input
          ref={inputRef}
          type="file"
          accept="image/jpeg,image/png,image/webp"
          capture="user"
          className="hidden"
          onChange={(e) => e.target.files?.[0] && onPick(e.target.files[0])}
        />
      </div>

      {user.face_photo_path && (
        <p className="text-xs text-center text-muted-foreground">Saved. Click the button below to continue.</p>
      )}
      <Button disabled={!user.face_photo_path || loading} onClick={() => onDone(user)} className="w-full">
        Continue
      </Button>
    </div>
  );
}
