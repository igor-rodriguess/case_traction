/**
 * Cliente da API de investigação.
 *
 * Única porta de entrada de dados da aplicação. O frontend fala com a API e
 * nunca com o Supabase: a credencial de banco não existe neste lado, e a
 * proveniência continua sendo escrita por quem tem autoridade para isso.
 *
 * Não há fallback para mock. Se a API cair, a interface diz que caiu — esconder
 * a falha atrás de dado falso é pior que mostrar o erro.
 */

import type { Evaluation } from './eval-types';
import type { Investigation } from './investigation-types';
import { adaptDossier, adaptSummary, type InvestigationSummary } from './api-adapters';

export const API_BASE_URL =
  (typeof process !== 'undefined' && process.env?.NEXT_PUBLIC_API_BASE_URL) ||
  'http://127.0.0.1:8000';

export class ApiError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly detail?: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: Object.assign({ 'Content-Type': 'application/json' }, init?.headers),
    });
  } catch {
    throw new ApiError(
      'UNREACHABLE',
      'Não foi possível conectar ao serviço de investigação.',
      'Verifique se a API está no ar.',
    );
  }

  if (!response.ok) {
    let code = 'UNKNOWN';
    let message = 'A requisição falhou.';
    let detail: string | undefined;
    try {
      // O handler global da API embrulha o detalhe estruturado em `message`.
      // Aceitar as duas formas evita acoplar o cliente a esse detalhe.
      const body = (await response.json()) as {
        detail?: { code?: string; message?: string; detail?: string };
        message?: { code?: string; message?: string; detail?: string } | string;
        code?: string;
      };
      const nested = typeof body.message === 'object' ? body.message : undefined;
      const flat = typeof body.message === 'string' ? body.message : 'A requisição falhou.';
      const payload = body.detail ?? nested ?? { code: body.code, message: flat };
      code = payload.code ?? code;
      message = payload.message ?? message;
      detail = typeof payload.detail === 'string' ? payload.detail : undefined;
    } catch {
      /* resposta sem corpo JSON: mantém a mensagem genérica */
    }
    throw new ApiError(code, message, detail, response.status);
  }

  return (await response.json()) as T;
}

// --------------------------------------------------------------------------

export interface Health {
  api: string;
  database: string;
  running_investigations: number;
  checked_at: string;
}

export interface AcceptedInvestigation {
  investigation_id: string;
  case_id: string;
  phase: string;
  created_at: string;
}

export const api = {
  health: () => request<Health>('/api/v1/health'),

  list: async (): Promise<InvestigationSummary[]> => {
    const rows = await request<Record<string, unknown>[]>('/api/v1/investigations?limit=100');
    return rows.map(adaptSummary);
  },

  /** Dossiê completo já traduzido para os tipos que os componentes consomem. */
  get: async (
    caseId: string,
  ): Promise<{ investigation: Investigation; evaluation?: Evaluation; running: boolean }> => {
    const raw = await request<Record<string, unknown>>(
      `/api/v1/investigations/${encodeURIComponent(caseId)}`,
    );
    return adaptDossier(raw);
  },

  create: (payload: { message: string; tenant_ref?: string; asset_refs?: string[] }) =>
    request<AcceptedInvestigation>('/api/v1/investigations', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
};
