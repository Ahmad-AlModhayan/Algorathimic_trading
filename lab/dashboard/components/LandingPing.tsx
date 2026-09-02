"use client";

import { useEffect } from "react";
import { api } from "@/lib/api";

/** Counts one landing view (no cookies, no identifiers). `?ref=` tags the source post. */
export default function LandingPing() {
  useEffect(() => {
    const ref = new URLSearchParams(window.location.search).get("ref");
    const t = setTimeout(() => {
      api.landingEvent(ref).catch(() => {});
    }, 0);
    return () => clearTimeout(t);
  }, []);
  return null;
}
