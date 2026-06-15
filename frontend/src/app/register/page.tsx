"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { register } from "@/lib/api";
import { useAuth } from "@/lib/auth-store";

export default function RegisterPage() {
  const router = useRouter();
  const setSession = useAuth((s) => s.setSession);
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    try {
      const res = await register({ email, username, password, display_name: displayName || undefined });
      setSession(res.access_token, res.user);
      router.push("/onboarding");
    } catch (err: any) {
      toast.error(err?.response?.data?.detail ?? "Registration failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen flex items-center justify-center p-6">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Create your twin</CardTitle>
          <CardDescription>It takes 5 minutes.</CardDescription>
        </CardHeader>
        <form onSubmit={onSubmit}>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="username">Username</Label>
              <Input id="username" required pattern="[a-zA-Z0-9_.-]{3,64}" value={username} onChange={(e) => setUsername(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="displayName">Display name (optional)</Label>
              <Input id="displayName" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input id="password" type="password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} />
            </div>
          </CardContent>
          <CardFooter className="flex flex-col gap-3">
            <Button type="submit" disabled={loading} className="w-full">
              {loading ? "Creating…" : "Create account"}
            </Button>
            <p className="text-sm text-muted-foreground">
              Have one? <Link href="/login" className="text-primary hover:underline">Log in</Link>
            </p>
          </CardFooter>
        </form>
      </Card>
    </main>
  );
}
