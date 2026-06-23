import type { Metadata } from "next";
import "./globals.css";
import { Toaster } from "sonner";
import { AuthSync } from "@/components/auth-sync";

export const metadata: Metadata = {
  title: "MirrorSelf",
  description: "Your digital twin: face, voice, personality, memory.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body>
        <AuthSync />
        {children}
        <Toaster theme="dark" position="top-right" richColors />
      </body>
    </html>
  );
}
