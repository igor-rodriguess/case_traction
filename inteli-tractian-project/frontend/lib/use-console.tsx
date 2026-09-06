'use client';

/**
 * Estado de dados do console, vindo da API.
 *
 * Um contexto único evita ter que passar as investigações por props em cada
 * view — os componentes continuam exatamente como estavam, só passam a ler
 * daqui em vez do módulo de mocks.
 *
 * O polling existe porque a execução é assíncrona: o POST devolve o
 * identificador em 202 e o pipeline segue em segundo plano. Enquanto o caso não
 * tiver estado terminal, a página relê a cada 2,5 s; quando termina, para.
 * Nenhum progresso é inventado — a fase mostrada é a que o backend registrou.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { api, ApiError } from './api';
import type { InvestigationSummary } from './api-adapters';
import type { Evaluation } from './eval-types';
import type { Investigation } from './investigation-types';

const POLL_MS = 2500;

export interface Dossier {
  investigation: Investigation;
  evaluation?: Evaluation;
  running: boolean;
}

interface ConsoleState {
  summaries: InvestigationSummary[];
  loading: boolean;
  error: ApiError | null;
  reload: () => void;
}

const ConsoleContext = createContext<ConsoleState | null>(null);

export function ConsoleProvider({ children }: { children: React.ReactNode }) {
  const [summaries, setSummaries] = useState<InvestigationSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [tick, setTick] = useState(0);

  const reload = useCallback(() => setTick((value) => value + 1), []);

  useEffect(() => {
    let active = true;
    api
      .list()
      .then((rows) => {
        if (!active) return;
        setSummaries(rows);
        setError(null);
      })
      .catch((exc) => active && setError(exc as ApiError))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [tick]);

  // Enquanto houver caso em execução, a lista se atualiza sozinha. O intervalo é
  // um sistema externo: o efeito só o registra e o desmonta.
  const hasRunning = summaries.some((row) => row.running || !row.terminal_state);
  useEffect(() => {
    if (!hasRunning) return undefined;
    const id = setInterval(() => reload(), POLL_MS);
    return () => clearInterval(id);
  }, [hasRunning, reload]);

  const value = useMemo(
    () => ({ summaries, loading, error, reload }),
    [summaries, loading, error, reload],
  );
  return <ConsoleContext.Provider value={value}>{children}</ConsoleContext.Provider>;
}

export function useConsole(): ConsoleState {
  const value = useContext(ConsoleContext);
  if (!value) throw new Error('useConsole precisa estar dentro de ConsoleProvider');
  return value;
}

/** Fila de revisão: uma regra só, derivada do que o backend decidiu. */
export function reviewQueueOf(summaries: InvestigationSummary[]): InvestigationSummary[] {
  return summaries.filter(
    (row) => row.human_review_required || row.final_verdict === 'REJECTED',
  );
}

/**
 * Dossiê de um caso, com polling enquanto a execução não termina.
 */
export function useDossier(caseId: string | undefined) {
  const [state, setState] = useState<{
    dossier: Dossier | null;
    error: ApiError | null;
    loading: boolean;
    forCase: string | undefined;
  }>({ dossier: null, error: null, loading: Boolean(caseId), forCase: caseId });
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Descarta o dossiê anterior ainda no render, sem setState em efeito.
  if (state.forCase !== caseId) {
    setState({ dossier: null, error: null, loading: Boolean(caseId), forCase: caseId });
  }

  const setDossier = useCallback(
    (dossier: Dossier) => setState((prev) => ({ ...prev, dossier, error: null, loading: false })),
    [],
  );
  const setError = useCallback(
    (error: ApiError | null) => setState((prev) => ({ ...prev, error, loading: false })),
    [],
  );
  const setLoading = useCallback(
    (loading: boolean) => setState((prev) => ({ ...prev, loading })),
    [],
  );

  useEffect(() => {
    if (!caseId) return undefined;

    let active = true;

    const stop = () => {
      if (timer.current) clearTimeout(timer.current);
      timer.current = null;
    };

    const load = () => {
      api
        .get(caseId)
        .then((next) => {
          if (!active) return;
          setDossier(next);
          setError(null);
          setLoading(false);
          // Para quando o caso chega a um desfecho e não há mais nada mudando.
          const done = Boolean(next.investigation.terminal_state) && !next.running;
          if (!done) timer.current = setTimeout(load, POLL_MS);
        })
        .catch((exc) => {
          if (!active) return;
          setError(exc as ApiError);
          setLoading(false);
          // Erro permanente encerra o ciclo; 404 e falha de rede não se resolvem
          // sozinhos e não vale manter requisição em laço.
          stop();
        });
    };

    load();
    return () => {
      active = false;
      stop();
    };
  }, [caseId, setDossier, setError, setLoading]);

  return { dossier: state.dossier, loading: state.loading, error: state.error };
}
