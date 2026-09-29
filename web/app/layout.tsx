import type {Metadata} from 'next';
import {Toaster} from '@/components/ui/sonner';
import {ThemeProvider} from '@/components/common/layout/ThemeProvider';
import {AuthProvider} from '@/lib/auth-context';
import {I18nProvider} from '@/lib/i18n/provider';
import {withBasePath} from '@/lib/base-path';
import './globals.css';

/**
 * 字体：不用 `next/font/google`。
 *
 * 原实现用 next/font 引入 Inter 与 Noto_Sans_SC，那会在**构建期**去
 * fonts.googleapis.com 下载字体（Noto Sans SC 是 CJK，按 unicode-range 切成上百个
 * 子集文件）。网络受限时这一步会让整个 `next build` 以
 * `An error occurred in next/font` 失败，而且报错完全看不出是网络问题。
 *
 * 现在改为纯系统字体栈，变量 `--font-inter` / `--font-noto-sans-sc` 在
 * `globals.css` 的 `:root` 里定义，Tailwind 的 `--font-sans` 照常解析。视觉差异仅是
 * 字形回落到系统 CJK 字体（Windows→微软雅黑、macOS→苹方）。
 */

export const metadata: Metadata = {
  title: {
    template: '%s - WorkBuddy Manager',
    default: 'WorkBuddy Manager',
  },
  /**
   * 站点描述用英文：它是构建期写进静态 HTML 的元数据，无法跟随运行时语言切换
   * （管理端本身不做语言路由，见 lib/i18n/config.ts 的说明）。选英文是因为
   * 分享卡片 / 搜索引擎抓取时它面向的受众最广；界面内的文案全部走 i18n。
   */
  description: 'WorkBuddy Manager - Tencent CodeBuddy account pool console and OpenAI-compatible gateway',
  // 图标 / 清单的 URL 也要带部署前缀（PR #60 评审补漏）：Next 只给 `_next`
  // 静态资源与 next/link 跳转补 basePath，**不会**改写 metadata 里的这些字符串
  // ——实测子路径部署下产物里仍是 `href="/favicon/..."`，会被请求到域名根（通常是
  // 另一个站点）而 404，表现为「站点图标不见了、PWA 清单取不到」。根路径部署时
  // withBasePath 原样返回，行为不变。
  manifest: withBasePath('/favicon/site.webmanifest'),
  icons: {
    icon: [
      {url: withBasePath('/favicon/favicon-32x32.png'), sizes: '32x32', type: 'image/png'},
      {url: withBasePath('/favicon/favicon-16x16.png'), sizes: '16x16', type: 'image/png'},
    ],
    shortcut: withBasePath('/favicon/favicon.ico'),
    apple: withBasePath('/favicon/apple-touch-icon.png'),
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="zh-CN"
      className="hide-scrollbar font-sans"
      suppressHydrationWarning
    >
      <body
        className="hide-scrollbar font-sans antialiased"
      >
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          <I18nProvider>
            <AuthProvider>
              {children}
              <Toaster />
            </AuthProvider>
          </I18nProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
