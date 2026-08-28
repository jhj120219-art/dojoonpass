import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { textSizeBootScript } from "@/lib/textSize";

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
      <head>
        {/* 큰글씨 설정을 **첫 페인트 전에** 반영한다.
            없으면 기본 크기로 한 번 그려진 뒤 커져서 글자가 눈에 띄게 튄다(FOUC).
            스크립트 본문은 `@/lib/textSize` 가 자기 상수로 만들어 낸다 — 배율과
            저장키를 여기에 다시 적지 않는다(정본 하나). 사용자 입력이 들어가지
            않는 고정 문자열이라 주입 위험이 없다. */}
        <script dangerouslySetInnerHTML={{ __html: textSizeBootScript() }} />
      </head>
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
