"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { login } from "@/lib/api";
import { useAuth } from "@/lib/auth-store";

export default function LoginPage() {
  const router = useRouter();
  const setSession = useAuth((s) => s.setSession);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    try {
      const res = await login({ email, password });
      setSession(res.access_token, res.user);
      router.push(res.user.is_onboarded ? "/chat" : "/onboarding");
    } catch (err: any) {
      toast.error(err?.response?.data?.detail ?? "Login failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen flex items-center justify-center p-6">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Welcome back</CardTitle>
          <CardDescription>Log in to talk to your twin.</CardDescription>
        </CardHeader>
        <form onSubmit={onSubmit}>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input id="password" type="password" required value={password} onChange={(e) => setPassword(e.target.value)} />
            </div>
          </CardContent>
          <CardFooter className="flex flex-col gap-3">
            <Button type="submit" disabled={loading} className="w-full">
              {loading ? "Logging in…" : "Log in"}
            </Button>
            <p className="text-sm text-muted-foreground">
              New here? <Link href="/register" className="text-primary hover:underline">Create an account</Link>
            </p>
          </CardFooter>
        </form>
      </Card>
    </main>
  );
}
