"use client";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { submitQuiz } from "@/lib/api";
import type { UserPrivate, PersonalityProfile } from "@/lib/api";

const QUESTIONS: Array<{ key: keyof PersonalityProfile; label: string; placeholder: string; multiline?: boolean }> = [
  { key: "values", label: "What do you value most? (3-5 words)", placeholder: "curiosity, family, craft, honesty…" },
  { key: "communication_style", label: "How do you communicate?", placeholder: "direct, gentle, sarcastic, structured…" },
  { key: "humor", label: "What's your humor like?", placeholder: "dry, absurdist, dad-joke, observational…" },
  { key: "fears", label: "What do you fear?", placeholder: "being ordinary, losing people I love, regret…" },
  { key: "dreams", label: "What do you dream of becoming?", placeholder: "someone who makes weird useful things…" },
];

export function StepQuiz({ token, user, onDone }: { token: string; user: UserPrivate; onDone: (u: UserPrivate) => void }) {
  const [values, setValues] = useState("");
  const [communicationStyle, setCommunicationStyle] = useState("");
  const [humor, setHumor] = useState("");
  const [fears, setFears] = useState("");
  const [dreams, setDreams] = useState("");
  const [loading, setLoading] = useState(false);

  async function onSubmit() {
    const profile: PersonalityProfile = {
      values: values.split(",").map((s) => s.trim()).filter(Boolean),
      communication_style: communicationStyle.trim() || null,
      humor: humor.trim() || null,
      fears: fears.split(",").map((s) => s.trim()).filter(Boolean),
      dreams: dreams.split(",").map((s) => s.trim()).filter(Boolean),
    };
    if (profile.values.length === 0) {
      toast.error("Please share at least one value");
      return;
    }
    setLoading(true);
    try {
      const updated = await submitQuiz(token, profile);
      onDone(updated);
    } catch (err: any) {
      toast.error(err?.response?.data?.detail ?? "Could not save profile");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold">5 questions that define you</h2>
        <p className="text-sm text-muted-foreground">
          Your twin will use these to choose how to talk to you. Be honest.
        </p>
      </div>

      {[
        { val: values, set: setValues, ...QUESTIONS[0] },
        { val: communicationStyle, set: setCommunicationStyle, ...QUESTIONS[1] },
        { val: humor, set: setHumor, ...QUESTIONS[2] },
        { val: fears, set: setFears, ...QUESTIONS[3] },
        { val: dreams, set: setDreams, ...QUESTIONS[4] },
      ].map((q, i) => (
        <div key={i} className="space-y-2">
          <Label>{q.label}</Label>
          <Input
            value={q.val}
            onChange={(e) => q.set(e.target.value)}
            placeholder={q.placeholder}
          />
        </div>
      ))}

      <Button onClick={onSubmit} disabled={loading} className="w-full">
        {loading ? "Saving…" : "Continue"}
      </Button>
    </div>
  );
}
