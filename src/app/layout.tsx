import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

// 서비스명은 "콕찰"로 확정되어 있다(docs/decision-log.md "Service Name").
// create-next-app 기본값("Create Next App")이 그대로 남아 브라우저 탭·공유 미리보기에
// 노출되고 있어 확정된 명칭으로 교체한다.
export const metadata: Metadata = {
  title: "콕찰 — 법원경매 검색",
  description: "전국 법원경매 물건을 검색하고 상세 정보와 등기부를 확인하는 서비스",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  // lang: 화면 문구가 전부 한국어인데 lang="en"이면 스크린리더 발음/번역 제안이 어긋난다.
  return (
    <html
      lang="ko"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
