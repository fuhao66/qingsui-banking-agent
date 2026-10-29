import type { Metadata } from "next";
import { ServiceWorkerRegistration } from "@/components/service-worker-registration";
import "./globals.css";

export const metadata: Metadata = {
  title: "青穗银行 · AI 智能体",
  description: "可解释、可审计的银行 AI 智能体演示平台",
  manifest: "/manifest.webmanifest",
  appleWebApp: { capable: true, statusBarStyle: "default", title: "青穗银行" },
  icons: { icon: "/banking-agent-icon.svg", apple: "/banking-agent-icon.svg" },
};

export const viewport = { themeColor: "#105a3d", width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        <ServiceWorkerRegistration />
        {children}
      </body>
    </html>
  );
}
