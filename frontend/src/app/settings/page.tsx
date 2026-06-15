"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { LogOut, Save, ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/lib/auth-store";
import { updateMe } from "@/lib/api";

export default function SettingsPage() {
  const router = useRouter();
  const { token, user, setUser, logout } = useAuth();
  const [displayName, setDisplayName] = useState("");
  const [bio, setBio] = useState("");
  const [isPublic, setIsPublic] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!token) router.push("/login");
    if (user) {
      setDisplayName(user.display_name ?? "");
      setBio(user.bio ?? "");
      setIsPublic(user.is_public);
    }
  }, [token, user, router]);

  async function save() {
    if (!token) return;
    setSaving(true);
    try {
      const updated = await updateMe(token, { display_name: displayName, bio, is_public: isPublic });
      setUser(updated);
      toast.success("Saved");
    } catch (err: any) {
      toast.error(err?.response?.data?.detail ?? "Save failed");
    } finally {
      setSaving(false);
    }
  }

  if (!token || !user) return null;

  const publicUrl = typeof window !== "undefined" ? `${window.location.origin}/u/${user.username}` : `/u/${user.username}`;

  return (
    <main className="min-h-screen container max-w-2xl py-10 space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Settings</h1>
        <p className="text-sm text-muted-foreground">Manage how your twin appears to the world.</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Profile</CardTitle>
          <CardDescription>Visible on your public twin page.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label>Display name</Label>
            <Input value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label>Bio</Label>
            <Textarea value={bio} onChange={(e) => setBio(e.target.value)} maxLength={500} />
          </div>
          <div className="flex items-center gap-2">
            <input
              id="isPublic"
              type="checkbox"
              checked={isPublic}
              onChange={(e) => setIsPublic(e.target.checked)}
              className="h-4 w-4"
            />
            <Label htmlFor="isPublic" className="cursor-pointer">
              Make my twin public — anyone with the link can talk to it.
            </Label>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Twin</CardTitle>
          <CardDescription>Status: <span className="font-mono">{user.twin_status}</span></CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          <div className="text-sm">
            <span className="text-muted-foreground">Public URL:</span>{" "}
            <a className="text-primary inline-flex items-center gap-1" href={publicUrl} target="_blank" rel="noreferrer">
              {publicUrl} <ExternalLink className="h-3 w-3" />
            </a>
          </div>
          <div className="text-sm text-muted-foreground">{user.conversation_count} conversations so far.</div>
        </CardContent>
      </Card>

      <div className="flex justify-between">
        <Button variant="outline" onClick={() => { logout(); router.push("/"); }}>
          <LogOut className="h-4 w-4 mr-2" /> Log out
        </Button>
        <Button onClick={save} disabled={saving}>
          <Save className="h-4 w-4 mr-2" /> {saving ? "Saving…" : "Save changes"}
        </Button>
      </div>
    </main>
  );
}
