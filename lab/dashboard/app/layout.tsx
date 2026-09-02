import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "لوحة المحتوى",
  description: "مراجعة المنشورات، التقويم، القمع، حالة المهام",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ar" dir="rtl">
      <body className="min-h-screen bg-zinc-50 text-zinc-900 antialiased">{children}</body>
    </html>
  );
}
