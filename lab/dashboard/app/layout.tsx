import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: process.env.NEXT_PUBLIC_BRAND_NAME ?? "مختبر الاستراتيجيات",
  description: "اكتب قاعدتك وشاهد نتيجتها الحقيقية على ثلاث سنوات من البيانات، بعد الرسوم.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ar" dir="rtl">
      <body className="min-h-screen bg-zinc-50 text-zinc-900 antialiased">{children}</body>
    </html>
  );
}
