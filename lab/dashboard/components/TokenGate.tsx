"use client";

import { useState } from "react";
import { setToken } from "@/lib/api";

export default function TokenGate({ onSaved }: { onSaved: () => void }) {
  const [value, setValue] = useState("");
  return (
    <form
      className="flex flex-wrap items-center gap-2 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm"
      onSubmit={(e) => {
        e.preventDefault();
        if (!value.trim()) return;
        setToken(value.trim());
        onSaved();
      }}
    >
      <span>رمز الإدارة (LAB_ADMIN_TOKEN):</span>
      <input
        type="password"
        className="rounded border border-zinc-300 px-2 py-1"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        autoComplete="off"
      />
      <button className="rounded bg-zinc-800 px-3 py-1 text-white">دخول</button>
    </form>
  );
}
