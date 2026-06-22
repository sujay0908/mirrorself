"use client";
import { useState } from "react";
import { toast } from "sonner";
import { Loader2, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { generateAvatar } from "@/lib/api";
import type { UserPrivate } from "@/lib/api";

export function StepGenerate({ token, user, onDone }: { token: string; user: UserPrivate; onDone: (u: UserPrivate) => void }) {
  const [loading, setLoading] = useState(false);

  async function start() {
    setLoading(true);
    try {
      const updated = await generateAvatar(token);
      onDone(updated);
    } catch (err: any) {
      toast.error(err?.response?.data?.detail ?? "Generation failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-5">
      <div className="text-center space-y-2">
        <Sparkles className="h-10 w-10 mx-auto text-primary" />
        <h2 className="text-lg font-semibold">Bring your twin to life</h2>
        <p className="text-sm text-muted-foreground">
          We&rsquo;ll generate your talking-head preview. This can take a minute on a GPU, longer on CPU.
        </p>
      </div>

      {user.avatar_video_path && (
        <video src={user.avatar_video_path} controls className="w-full rounded-md" />
      )}

      <Button onClick={start} disabled={loading} className="w-full" size="lg">
        {loading ? (
          <>
            <Loader2 className="h-4 w-4 mr-2 animate-spin" /> Generating…
          </>
        ) : user.avatar_video_path ? (
          "Regenerate avatar"
        ) : (
          "Generate my avatar"
        )}
      </Button>
    </div>
  );
}
