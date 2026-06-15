import Link from "next/link";
import { Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function Home() {
  return (
    <main className="min-h-screen flex flex-col">
      <header className="container flex items-center justify-between py-6">
        <div className="flex items-center gap-2 font-semibold text-xl">
          <Sparkles className="h-5 w-5 text-primary" />
          <span>MirrorSelf</span>
        </div>
        <nav className="flex items-center gap-3">
          <Link href="/login">
            <Button variant="ghost">Log in</Button>
          </Link>
          <Link href="/register">
            <Button>Get started</Button>
          </Link>
        </nav>
      </header>

      <section className="container flex-1 flex flex-col items-center justify-center text-center py-20">
        <h1 className="text-5xl md:text-6xl font-bold tracking-tight max-w-3xl">
          A digital twin that <span className="text-primary">talks</span> like you,
          <br /> thinks like you, remembers you.
        </h1>
        <p className="mt-6 text-lg text-muted-foreground max-w-2xl">
          Upload a face, record 30 seconds of voice, share how you see the world.
          MirrorSelf builds a real-time avatar that responds in your voice and on your face.
        </p>
        <div className="mt-10 flex gap-3">
          <Link href="/register"><Button size="lg">Create my twin</Button></Link>
          <Link href="/u/demo"><Button size="lg" variant="outline">See a public twin</Button></Link>
        </div>

        <div className="mt-20 grid md:grid-cols-3 gap-6 max-w-5xl text-left">
          {[
            { title: "Voice-cloned replies", body: "XTTS-v2 turns every AI response into audio in your actual voice." },
            { title: "Lip-synced avatar", body: "SadTalker animates your face photo so your twin can speak, smile, and react." },
            { title: "Memory that grows", body: "Every conversation extracts facts. Your twin gets to know you over time." },
          ].map((f) => (
            <div key={f.title} className="rounded-lg border bg-card p-6">
              <h3 className="font-semibold">{f.title}</h3>
              <p className="text-sm text-muted-foreground mt-2">{f.body}</p>
            </div>
          ))}
        </div>
      </section>

      <footer className="container py-6 text-sm text-muted-foreground">
        Built with Next.js, FastAPI, Claude, XTTS-v2, and SadTalker.
      </footer>
    </main>
  );
}
