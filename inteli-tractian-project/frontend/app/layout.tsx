import type { Metadata } from 'next';
import { Inter, Inter_Tight } from 'next/font/google';
import './globals.css';

const inter = Inter({ variable: '--font-inter', subsets: ['latin'] });
const interTight = Inter_Tight({ variable: '--font-inter-tight', subsets: ['latin'] });

export const metadata: Metadata = {
  title: 'Investigação com AI · Engenharia TRACTIAN',
  description: 'Bancada de revisão de investigações operacionais da Equipe de Engenharia TRACTIAN.',
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="pt-BR"><body className={`${inter.variable} ${interTight.variable}`}>{children}</body></html>;
}
