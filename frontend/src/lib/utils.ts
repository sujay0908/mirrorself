import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDate(d: string | Date) {
  return new Date(d).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function toAbsoluteUrl(path: string, base: string) {
  if (!path) return path;
  if (path.startsWith("http")) return path;
  return `${base.replace(/\/$/, "")}${path.startsWith("/") ? path : `/${path}`}`;
}
