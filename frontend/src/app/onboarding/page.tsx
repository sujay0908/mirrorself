"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Check, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { useAuth } from "@/lib/auth-store";
import { StepFace } from "./_steps/step-face";
import { StepVoice } from "./_steps/step-voice";
import { StepQuiz } from "./_steps/step-quiz";
import { StepGenerate } from "./_steps/step-generate";

const STEPS = [
  { key: "face", title: "Upload a face" },
  { key: "voice", title: "Record your voice" },
  { key: "quiz", title: "Tell us who you are" },
  { key: "generate", title: "Bring your twin to life" },
];

export default function OnboardingPage() {
  const router = useRouter();
  const { token, user, setUser } = useAuth();
  const [step, setStep] = useState(0);

  useEffect(() => {
    if (!token) router.push("/login");
  }, [token, router]);

  if (!token || !user) return null;

  const progress = ((step + 1) / STEPS.length) * 100;

  return (
    <main className="min-h-screen container py-10">
      <div className="max-w-2xl mx-auto space-y-6">
        <div>
          <h1 className="text-2xl font-semibold">Set up {user.username}&rsquo;s twin</h1>
          <p className="text-sm text-muted-foreground mt-1">Step {step + 1} of {STEPS.length}</p>
        </div>
        <Progress value={progress} />

        <div className="flex gap-2">
          {STEPS.map((s, i) => (
            <div
              key={s.key}
              className={`flex-1 rounded-md border px-3 py-2 text-xs flex items-center gap-2 ${
                i === step ? "border-primary text-primary" : i < step ? "border-primary/30 text-primary/70" : "text-muted-foreground"
              }`}
            >
              {i < step ? <Check className="h-3 w-3" /> : <span className="font-mono">{i + 1}</span>}
              <span className="truncate">{s.title}</span>
            </div>
          ))}
        </div>

        <Card>
          <CardContent className="pt-6">
            {step === 0 && <StepFace token={token} user={user} onDone={(u) => { setUser(u); setStep(1); }} />}
            {step === 1 && <StepVoice token={token} user={user} onDone={(u) => { setUser(u); setStep(2); }} />}
            {step === 2 && <StepQuiz token={token} user={user} onDone={(u) => { setUser(u); setStep(3); }} />}
            {step === 3 && <StepGenerate token={token} user={user} onDone={(u) => { setUser(u); toast.success("Twin ready!"); router.push("/chat"); }} />}
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
