'use client';

export default function ErrorState({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <main className="fatal-error" role="alert">
      <span className="fatal-error__code">Erro</span>
      <h1>Não foi possível exibir a investigação</h1>
      <p>
        A interface não conseguiu renderizar os dados atuais. Nenhum estado de investigação foi
        alterado.
      </p>
      <button type="button" className="button button--primary" onClick={reset} style={{ marginTop: 16 }}>
        Tentar novamente
      </button>
    </main>
  );
}
