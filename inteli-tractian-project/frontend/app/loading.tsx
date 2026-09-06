import { Skeleton } from '@/components/ui/skeleton';

export default function Loading() {
  return (
    <main className="loading-page" aria-busy="true" aria-label="Carregando a bancada de investigação">
      <Skeleton className="loading-title" />
      <Skeleton className="loading-strip" />
      <div>
        <Skeleton />
        <Skeleton />
      </div>
    </main>
  );
}
