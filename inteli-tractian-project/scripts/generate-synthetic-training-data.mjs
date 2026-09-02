import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const DESIGN_PATH = join(ROOT, "docs", "architecture", "04-6-synthetic-training-design.json");
const EXPECTED_PATHS = join(ROOT, "eval", "expected-paths.json");
const CASES_PATH = join(ROOT, "agent-input", "cases.json");
const OUTPUT_ROOT = join(ROOT, "datasets", "synthetic");
const DATASET_VERSION = "1.0.0";
const GENERATOR_VERSION = "1.0.0";
const GENERATOR_SEED = "tractian-synthetic-v1-2026-09-02";

const design = JSON.parse(readFileSync(DESIGN_PATH, "utf8"));
const expectedPaths = JSON.parse(readFileSync(EXPECTED_PATHS, "utf8"));
const officialCases = JSON.parse(readFileSync(CASES_PATH, "utf8"));

const splitConfig = {
  train: {
    understanding: 240,
    investigator: 400,
    assets: ["asset_H110", "asset_F115", "asset_C210", "asset_R310", "asset_M312", "asset_F520", "asset_P712", "asset_G715", "asset_F215", "asset_R610"],
    requestClasses: { contextualize: 60, investigate: 100, execute_or_handoff_recognition: 53, mixed_or_unclear: 27 },
    difficulty: { easy: 84, medium: 108, hard: 48 },
    investigatorDifficulty: { easy: 80, medium: 200, hard: 120 },
    decisions: { TOOL_CALL: 220, ASK_USER: 60, ANSWER: 80, ESCALATE: 40 },
    conditions: { complete_or_healthy: 80, partial: 53, inconclusive: 47, conflict: 47, unavailable_semantic: 40, transport_or_http_error: 40, missing_or_ambiguous: 33, tenant_or_permission: 33, stopping_or_redundancy: 27 },
    counterfactualPairs: { complete_vs_partial: 14, established_vs_learning: 14, good_vs_bad_data_quality: 14, permission_true_vs_false: 10, same_tenant_vs_other_tenant: 10, knowledge_found_vs_zero_results: 6, current_vs_stale_analysis: 6, critical_band_present_vs_missing: 6 },
  },
  dev: {
    understanding: 60,
    investigator: 100,
    assets: ["asset_B211", "asset_S425", "asset_X216"],
    requestClasses: { contextualize: 15, investigate: 25, execute_or_handoff_recognition: 13, mixed_or_unclear: 7 },
    difficulty: { easy: 21, medium: 27, hard: 12 },
    investigatorDifficulty: { easy: 20, medium: 50, hard: 30 },
    decisions: { TOOL_CALL: 55, ASK_USER: 15, ANSWER: 20, ESCALATE: 10 },
    conditions: { complete_or_healthy: 20, partial: 14, inconclusive: 11, conflict: 12, unavailable_semantic: 10, transport_or_http_error: 10, missing_or_ambiguous: 8, tenant_or_permission: 9, stopping_or_redundancy: 6 },
    counterfactualPairs: { complete_vs_partial: 3, established_vs_learning: 3, good_vs_bad_data_quality: 3, permission_true_vs_false: 3, same_tenant_vs_other_tenant: 3, knowledge_found_vs_zero_results: 2, current_vs_stale_analysis: 1, critical_band_present_vs_missing: 2 },
  },
  holdout: {
    understanding: 60,
    investigator: 100,
    assets: ["asset_C510", "asset_M428", "asset_M612"],
    requestClasses: { contextualize: 15, investigate: 25, execute_or_handoff_recognition: 14, mixed_or_unclear: 6 },
    difficulty: { easy: 21, medium: 27, hard: 12 },
    investigatorDifficulty: { easy: 20, medium: 50, hard: 30 },
    decisions: { TOOL_CALL: 55, ASK_USER: 15, ANSWER: 20, ESCALATE: 10 },
    conditions: { complete_or_healthy: 20, partial: 13, inconclusive: 12, conflict: 11, unavailable_semantic: 10, transport_or_http_error: 10, missing_or_ambiguous: 9, tenant_or_permission: 8, stopping_or_redundancy: 7 },
    counterfactualPairs: { complete_vs_partial: 3, established_vs_learning: 3, good_vs_bad_data_quality: 3, permission_true_vs_false: 2, same_tenant_vs_other_tenant: 2, knowledge_found_vs_zero_results: 2, current_vs_stale_analysis: 3, critical_band_present_vs_missing: 2 },
  },
};

const toolCatalog = {
  get_asset_context: ["Consulta identidade, hierarquia e configuração do ativo.", { type: "object", required: ["asset_id"], additionalProperties: false, properties: { asset_id: { type: "string" } } }],
  list_asset_analyses: ["Lista análises de um ativo para descobrir candidatos.", { type: "object", required: ["asset_id"], additionalProperties: false, properties: { asset_id: { type: "string" }, status: { enum: ["current", "stale", "pending", "inconclusive"] } } }],
  get_analysis_details: ["Consulta achados e evidências de uma análise identificada.", { type: "object", required: ["analysis_id"], additionalProperties: false, properties: { analysis_id: { type: "string" } } }],
  get_asset_baseline: ["Consulta a referência histórica de um ativo.", assetPointSchema()],
  get_asset_rms: ["Consulta a evolução agregada da vibração RMS.", assetPointSchema()],
  get_asset_spectrum: ["Consulta picos e bandas do espectro.", assetPointSchema()],
  get_asset_data_quality: ["Consulta completude, frescor e qualidade dos dados.", assetPointSchema()],
  get_model_capabilities: ["Consulta cobertura, requisitos e estado do modelo.", { type: "object", required: ["model_id"], additionalProperties: false, properties: { model_id: { type: "string" } } }],
  search_industrial_knowledge: ["Busca referências industriais por termos objetivos.", { type: "object", required: ["query"], additionalProperties: false, properties: { query: { type: "string" }, knowledge_type: { enum: ["procedure", "glossary", "guidance"] } } }],
  get_knowledge_document: ["Recupera um documento industrial conhecido.", { type: "object", required: ["doc_id"], additionalProperties: false, properties: { doc_id: { type: "string" } } }],
};

const toolNames = Object.keys(toolCatalog);
const components = ["motor auxiliar", "ventilador de resfriamento", "bomba de circulação", "redutor secundário", "compressor de serviço", "spindle de acabamento", "exaustor", "refiner", "misturador", "transportador"];
const signals = ["vibração RMS", "espectro axial", "temperatura do mancal", "qualidade do sinal", "tendência radial", "ruído de banda larga"];
const timeRefs = ["desde o último turno", "nas últimas seis horas", "depois da parada programada", "desde a troca de carga", "nesta semana"];
const phrasings = ["Você consegue verificar", "Preciso entender", "Pode confirmar com os dados", "Quero uma avaliação objetiva de", "Antes de concluir, verifique"];
const operatingContexts = ["em regime nominal", "durante a aceleração", "sob carga estável", "no turno noturno", "após a limpeza", "com carga variável", "depois de ajuste operacional", "durante a desaceleração", "na partida a frio", "após inspeção de rotina", "em baixa rotação", "próximo da carga máxima"];

function assetPointSchema() {
  return { type: "object", required: ["asset_id"], additionalProperties: false, properties: { asset_id: { type: "string" }, point_id: { type: ["string", "null"] } } };
}

function expandCounts(counts) {
  return Object.entries(counts).flatMap(([value, count]) => Array.from({ length: count }, () => value));
}

function rotate(values, offset) {
  const normalized = offset % values.length;
  return values.slice(normalized).concat(values.slice(0, normalized));
}

function sha256(content) {
  return createHash("sha256").update(content).digest("hex");
}

function stableId(prefix, split, index) {
  return `${prefix}_${split}_${String(index + 1).padStart(4, "0")}`;
}

function tenantFor(split, index) {
  return `tenant_syn_${split}_${String((index % 7) + 1).padStart(2, "0")}`;
}

function makeUnderstanding(split, config) {
  const classes = rotate(expandCounts(config.requestClasses), split === "train" ? 17 : split === "dev" ? 5 : 11);
  const difficulties = rotate(expandCounts(config.difficulty), split === "train" ? 31 : split === "dev" ? 9 : 19);
  const splitOffset = split === "train" ? 0 : split === "dev" ? 3 : 7;
  return Array.from({ length: config.understanding }, (_, index) => {
    const requestClass = classes[index];
    const difficulty = difficulties[index];
    const asset = config.assets[index % config.assets.length];
    const secondAsset = config.assets[(index + 1) % config.assets.length];
    const component = components[(index + Math.floor(index / config.assets.length) + splitOffset) % components.length];
    const signal = signals[(index * 5 + Math.floor(index / 7) + 1 + splitOffset) % signals.length];
    const timeRef = timeRefs[(index * 2 + Math.floor(index / 11) + 2 + splitOffset) % timeRefs.length];
    const operatingContext = operatingContexts[(index * 7 + Math.floor(index / 3) + splitOffset) % operatingContexts.length];
    const phrasing = phrasings[index % phrasings.length];
    const multiAsset = difficulty === "hard" && index % 3 === 0;
    const ambiguous = requestClass === "mixed_or_unclear" || (difficulty !== "easy" && index % 11 === 0);
    const assets = multiAsset ? [asset, secondAsset] : [asset];
    const visibleAssets = ambiguous ? [] : assets;
    const target = understandingTarget({ requestClass, assets: visibleAssets, component, signal, timeRef, ambiguous, difficulty, index });
    return {
      sample_id: stableId("syn_u", split, index),
      schema_version: "1.0",
      schema_example_only: false,
      split,
      input: {
        message: understandingMessage({ requestClass, asset, secondAsset, component, signal, timeRef, operatingContext, phrasing, multiAsset, ambiguous, index }),
        available_context: {
          tenant_ref: tenantFor(split, index),
          asset_refs: ambiguous ? [] : assets,
          role: ["operator", "maintenance_analyst", "reliability_engineer"][index % 3],
          permissions: requestClass === "execute_or_handoff_recognition" ? ["read", "request_action"] : ["read"],
        },
      },
      target,
      training_tags: [requestClass, difficulty, multiAsset ? "multi_asset" : "single_asset", ambiguous ? "ambiguity_present" : "fully_scoped"],
      provenance: {
        synthetic_source: "deterministic_template_and_non_golden_asset_pool",
        counterfactual_group: null,
        golden_overlap_review: "pending",
      },
    };
  });
}

function understandingMessage({ requestClass, asset, secondAsset, component, signal, timeRef, operatingContext, phrasing, multiAsset, ambiguous, index }) {
  const ref = ambiguous ? "o equipamento reserva" : `${component} ${asset}`;
  if (requestClass === "contextualize") {
    return `${phrasing} o que significa ${signal} para ${ref} ${operatingContext} e qual fonte técnica deve orientar a interpretação ${timeRef}?`;
  }
  if (requestClass === "investigate") {
    const comparison = multiAsset ? ` Compare também com ${secondAsset}, mantendo as evidências separadas.` : "";
    return `${phrasing} se a mudança de ${signal} em ${ref}, ${operatingContext}, ${timeRef} representa desvio real ou limitação dos dados.${comparison}`;
  }
  if (requestClass === "execute_or_handoff_recognition") {
    const action = ["pedir reprocessamento", "encaminhar para especialista", "solicitar revisão da criticidade", "registrar uma escalação humana"][index % 4];
    return `${phrasing} a situação de ${ref} ${operatingContext}. Se houver evidência suficiente, quero ${action}; não execute nada sem a política apropriada.`;
  }
  return `${phrasing} aquele ${component} que comentamos: está estranho ${timeRef}, ${operatingContext}, talvez seja ${signal}. Veja isso e, se precisar mexer em algo, me diga primeiro.`;
}

function understandingTarget({ requestClass, assets, component, signal, timeRef, ambiguous, difficulty, index }) {
  const investigative = requestClass !== "contextualize";
  const asksAction = requestClass === "execute_or_handoff_recognition" || requestClass === "mixed_or_unclear";
  const schemaRequestClass = requestClass === "execute_or_handoff_recognition" ? "execute" : requestClass === "mixed_or_unclear" ? (index % 2 === 0 ? "mixed" : "unclear") : requestClass;
  const questionCount = difficulty === "hard" ? 2 : 1;
  const questions = [{ question_id: "q1", text: investigative ? `Há evidência suficiente para caracterizar a mudança de ${signal}?` : `Qual orientação técnica se aplica a ${signal}?`, kind: investigative ? "diagnosis" : "fact", depends_on: ambiguous ? ["asset_id"] : [] }];
  if (questionCount === 2) questions.push({ question_id: "q2", text: "A qualidade e a atualidade dos dados permitem confiar na conclusão?", kind: "comparison", depends_on: [] });
  return {
    request_class: schemaRequestClass,
    intents: [{
      intent_id: "intent_1",
      kind: asksAction ? "action_request" : investigative ? "investigative" : "informational",
      summary: investigative ? `Avaliar ${signal} do ${component} com evidência atual.` : `Explicar ${signal} com fonte aplicável.`,
      target_entities: assets,
      requested_outcome: asksAction ? "Avaliação e encaminhamento seguro do pedido de impacto." : "Resposta fundamentada e limitada pela evidência.",
    }],
    questions,
    entities: { assets, analyses: [], models: [], technical_terms: [signal], temporal_references: [timeRef] },
    investigation_targets: investigative ? ["asset context", signal, "baseline", "data quality"] : ["industrial knowledge", "asset applicability"],
    missing_information: ambiguous ? [{ field: "asset_id", reason_code: "AMBIGUOUS_ASSET_REFERENCE", blocking: true, suggested_question: "Qual é o identificador do equipamento que você quer avaliar?" }] : [],
    requested_actions: asksAction ? [{ capability: ["request_analysis_reprocessing", "request_specialist_analysis", "request_asset_config_update", "request_case_escalation"][index % 4], explicitly_requested: true, evidence_required: true }] : [],
    constraints: { tenant_scope_known: !ambiguous, permissions_known: requestClass !== "mixed_or_unclear", action_execution_allowed: false },
    confidence: ambiguous ? 0.68 : difficulty === "hard" ? 0.88 : 0.96,
  };
}

const pairSpecs = {
  complete_vs_partial: [{ condition: "complete_or_healthy", decision: "ANSWER", variant: "complete" }, { condition: "partial", decision: "TOOL_CALL", variant: "partial" }],
  established_vs_learning: [{ condition: "complete_or_healthy", decision: "ANSWER", variant: "established" }, { condition: "inconclusive", decision: "TOOL_CALL", variant: "learning" }],
  good_vs_bad_data_quality: [{ condition: "complete_or_healthy", decision: "ANSWER", variant: "good_quality" }, { condition: "partial", decision: "TOOL_CALL", variant: "bad_quality" }],
  permission_true_vs_false: [{ condition: "complete_or_healthy", decision: "ANSWER", variant: "permission_true" }, { condition: "tenant_or_permission", decision: "ESCALATE", variant: "permission_false" }],
  same_tenant_vs_other_tenant: [{ condition: "complete_or_healthy", decision: "TOOL_CALL", variant: "same_tenant" }, { condition: "tenant_or_permission", decision: "ASK_USER", variant: "other_tenant" }],
  knowledge_found_vs_zero_results: [{ condition: "complete_or_healthy", decision: "ANSWER", variant: "knowledge_found" }, { condition: "inconclusive", decision: "TOOL_CALL", variant: "knowledge_zero" }],
  current_vs_stale_analysis: [{ condition: "complete_or_healthy", decision: "ANSWER", variant: "current" }, { condition: "partial", decision: "TOOL_CALL", variant: "stale" }],
  critical_band_present_vs_missing: [{ condition: "complete_or_healthy", decision: "ANSWER", variant: "band_present" }, { condition: "inconclusive", decision: "ANSWER", variant: "band_missing" }],
};

function makeInvestigator(split, config) {
  const samples = [];
  let index = 0;
  for (const [pairType, count] of Object.entries(config.counterfactualPairs)) {
    for (let pairIndex = 0; pairIndex < count; pairIndex += 1) {
      const group = `cfg_${split}_${pairType}_${String(pairIndex + 1).padStart(3, "0")}`;
      const asset = config.assets[(index + pairIndex) % config.assets.length];
      const pairSamples = [];
      for (const spec of pairSpecs[pairType]) {
        pairSamples.push(investigatorSample({ split, index, asset, condition: spec.condition, decision: spec.decision, variant: spec.variant, counterfactualGroup: group, pairType }));
        index += 1;
      }
      pairSamples[1].input.request = structuredClone(pairSamples[0].input.request);
      samples.push(...pairSamples);
    }
  }

  const usedConditions = countBy(samples, (sample) => dominantCondition(sample));
  const remainingConditions = Object.fromEntries(Object.entries(config.conditions).map(([key, count]) => [key, count - (usedConditions[key] ?? 0)]));
  const usedDecisions = countBy(samples, (sample) => sample.target.decision);
  const remainingDecisions = Object.fromEntries(Object.entries(config.decisions).map(([key, count]) => [key, count - (usedDecisions[key] ?? 0)]));
  const flexibleConditions = ["partial", "inconclusive", "conflict", "unavailable_semantic", "transport_or_http_error"];
  const generalAssignments = [];

  let toolRemaining = remainingDecisions.TOOL_CALL;
  for (const condition of flexibleConditions) {
    const amount = Math.min(remainingConditions[condition], toolRemaining);
    addAssignments(generalAssignments, condition, "TOOL_CALL", amount);
    remainingConditions[condition] -= amount;
    toolRemaining -= amount;
  }
  if (toolRemaining > 0) {
    const amount = Math.min(remainingConditions.missing_or_ambiguous, toolRemaining);
    addAssignments(generalAssignments, "missing_or_ambiguous", "TOOL_CALL", amount);
    remainingConditions.missing_or_ambiguous -= amount;
    toolRemaining -= amount;
  }
  assert(toolRemaining === 0, `${split}: não foi possível alocar TOOL_CALL`);

  let askRemaining = remainingDecisions.ASK_USER;
  for (const condition of ["tenant_or_permission", "missing_or_ambiguous", "stopping_or_redundancy"]) {
    const amount = Math.min(remainingConditions[condition], askRemaining);
    addAssignments(generalAssignments, condition, "ASK_USER", amount);
    remainingConditions[condition] -= amount;
    askRemaining -= amount;
  }
  assert(askRemaining === 0, `${split}: não foi possível alocar ASK_USER`);

  let answerRemaining = remainingDecisions.ANSWER;
  for (const condition of ["stopping_or_redundancy", ...flexibleConditions]) {
    const amount = Math.min(remainingConditions[condition], answerRemaining);
    addAssignments(generalAssignments, condition, "ANSWER", amount);
    remainingConditions[condition] -= amount;
    answerRemaining -= amount;
  }
  assert(answerRemaining === 0, `${split}: não foi possível alocar ANSWER`);

  for (const [condition, amount] of Object.entries(remainingConditions)) addAssignments(generalAssignments, condition, "ESCALATE", amount);
  assert(generalAssignments.filter((entry) => entry.decision === "ESCALATE").length === remainingDecisions.ESCALATE, `${split}: quota ESCALATE inconsistente`);

  for (const assignment of rotate(generalAssignments, split === "train" ? 43 : split === "dev" ? 13 : 29)) {
    const asset = config.assets[index % config.assets.length];
    samples.push(investigatorSample({ split, index, asset, condition: assignment.condition, decision: assignment.decision, variant: "general", counterfactualGroup: null, pairType: null }));
    index += 1;
  }

  const difficulties = rotate(expandCounts(config.investigatorDifficulty), split === "train" ? 71 : split === "dev" ? 17 : 37);
  samples.forEach((sample, sampleIndex) => {
    sample.training_tags.push(difficulties[sampleIndex]);
    sample.training_tags = [...new Set(sample.training_tags)];
  });
  assert(samples.length === config.investigator, `${split}: total Investigator inesperado`);
  return samples;
}

function addAssignments(target, condition, decision, amount) {
  for (let index = 0; index < amount; index += 1) target.push({ condition, decision });
}

function investigatorSample({ split, index, asset, condition, decision, variant, counterfactualGroup, pairType }) {
  const sampleId = stableId("syn_i", split, index);
  const evidence = evidenceFor({ sampleId, asset, condition, variant, index });
  const invalidTenant = variant === "other_tenant" || condition === "tenant_or_permission";
  const stopping = condition === "stopping_or_redundancy";
  const missingAsset = condition === "missing_or_ambiguous" && decision === "ASK_USER";
  const actionRequest = pairType === "permission_true_vs_false" || (counterfactualGroup === null && index % 7 === 0);
  const request = {
    request_class: actionRequest ? "execute_or_handoff_recognition" : pairType?.includes("knowledge") ? "contextualize" : "investigate",
    questions: [requestQuestion({ asset, condition, variant, actionRequest, index })],
    asset_refs: missingAsset ? [] : [asset],
    missing_information: missingAsset ? ["asset_id"] : invalidTenant ? ["validated_tenant_scope"] : [],
  };
  const selectedTool = toolFor({ condition, variant, index });
  const availableNames = [...new Set([selectedTool, toolNames[(index + 3) % toolNames.length], toolNames[(index + 7) % toolNames.length]])];
  const target = targetFor({ decision, selectedTool, asset, condition, variant, evidence, actionRequest, index });
  return {
    sample_id: sampleId,
    schema_version: "1.0",
    schema_example_only: false,
    split,
    input: {
      request,
      current_evidence: evidence,
      available_tools: availableNames.map((name) => ({ name, description: toolCatalog[name][0], input_schema: toolCatalog[name][1] })),
      execution_state: {
        previous_calls: stopping ? [`get_asset_rms:{"asset_id":"${asset}"}`, `get_asset_rms:{"asset_id":"${asset}"}`] : evidence.map((item) => item.tool_name),
        remaining_tool_budget: stopping ? 0 : Math.max(1, 5 - (index % 4)),
        tenant_scope_validated: !invalidTenant,
        actions_enabled: false,
      },
    },
    target,
    training_tags: [condition, decision.toLowerCase(), variant, actionRequest ? "action_request_without_execution" : "read_only_request"],
    provenance: {
      synthetic_source: "deterministic_state_generator_and_non_golden_asset_pool",
      state_generator_version: GENERATOR_VERSION,
      counterfactual_group: counterfactualGroup,
      golden_overlap_review: "pending",
    },
  };
}

function requestQuestion({ asset, condition, variant, actionRequest, index }) {
  if (actionRequest) return `A evidência de ${asset} permite encaminhar com segurança o pedido de impacto, sem executá-lo autonomamente?`;
  if (variant.includes("knowledge")) return `Existe fonte industrial recuperada e aplicável para orientar ${asset}?`;
  if (condition === "conflict") return `Qual hipótese sobre ${asset} é melhor sustentada quando as fontes divergem?`;
  if (condition === "transport_or_http_error") return `É possível responder sobre ${asset} apesar da falha de transporte?`;
  if (condition === "stopping_or_redundancy") return `A investigação de ${asset} deve parar sem repetir chamadas?`;
  return `${phrasings[index % phrasings.length]} se ${asset} apresenta desvio de ${signals[(index * 5 + 1) % signals.length]} ${timeRefs[(index * 2 + 1) % timeRefs.length]}, ${operatingContexts[(index * 7 + 2) % operatingContexts.length]}, sustentado pelas evidências disponíveis.`;
}

function evidenceFor({ sampleId, asset, condition, variant, index }) {
  const id = (suffix) => `${sampleId}_ev_${suffix}`;
  const base = { tool_name: "get_asset_baseline", transport_ok: true, limitations: [] };
  if (condition === "complete_or_healthy") {
    const facts = variant === "permission_true" ? { asset_id: asset, permission: "request_only", action_executed: false }
      : variant === "knowledge_found" ? { asset_id: asset, document_found: true, applicability: "verified" }
      : variant === "band_present" ? { asset_id: asset, critical_band_observed: true, support: "sufficient" }
      : { asset_id: asset, baseline_state: variant === "established" ? "established" : "established", data_quality: variant === "good_quality" ? "good" : "good", health_state: "normal", analysis_state: variant === "current" ? "current" : "current" };
    return [{ evidence_id: id("1"), ...base, evidence_status: "complete", facts, limitations: [] }];
  }
  if (condition === "partial") {
    return [{ evidence_id: id("1"), ...base, evidence_status: "partial", facts: { asset_id: asset, baseline_state: variant === "stale" ? "invalidated" : "established", observed_fields: ["rms"] }, limitations: [variant === "bad_quality" ? "LOW_SIGNAL_QUALITY" : variant === "stale" ? "STALE_ANALYSIS" : "MISSING_SPECTRAL_BAND"] }];
  }
  if (condition === "inconclusive") {
    return [{ evidence_id: id("1"), ...base, evidence_status: "inconclusive", facts: { asset_id: asset, baseline_state: variant === "learning" ? "learning" : "unknown", result_count: variant === "knowledge_zero" ? 0 : undefined, critical_band_observed: variant === "band_missing" ? false : undefined }, limitations: [variant === "knowledge_zero" ? "NO_KNOWLEDGE_RESULT" : variant === "band_missing" ? "CRITICAL_BAND_NOT_OBSERVED" : "INSUFFICIENT_HISTORY"] }];
  }
  if (condition === "conflict") {
    return [
      { evidence_id: id("1"), tool_name: "get_analysis_details", evidence_status: "conflict", transport_ok: true, facts: { asset_id: asset, hypothesis: "alignment_deviation", source: "automatic" }, limitations: ["SOURCE_DISAGREEMENT"] },
      { evidence_id: id("2"), tool_name: "get_asset_spectrum", evidence_status: "conflict", transport_ok: true, facts: { asset_id: asset, hypothesis: "structural_looseness", source: "spectral_pattern" }, limitations: ["SOURCE_DISAGREEMENT"] },
    ];
  }
  if (condition === "unavailable_semantic") {
    return [{ evidence_id: id("1"), tool_name: "get_asset_rms", evidence_status: "unavailable", transport_ok: true, facts: { asset_id: asset, http_status: 200, series_available: false }, limitations: ["SEMANTICALLY_UNAVAILABLE"] }];
  }
  if (condition === "transport_or_http_error") {
    return [{ evidence_id: id("1"), tool_name: "get_asset_rms", evidence_status: "unavailable", transport_ok: false, facts: { asset_id: asset, http_status: index % 2 === 0 ? 503 : null }, limitations: [index % 2 === 0 ? "HTTP_503" : "TRANSPORT_TIMEOUT"] }];
  }
  if (condition === "stopping_or_redundancy") {
    return [{ evidence_id: id("1"), tool_name: "get_asset_rms", evidence_status: "inconclusive", transport_ok: true, facts: { asset_id: asset, repeated_result: true }, limitations: ["TOOL_BUDGET_EXHAUSTED", "NO_NEW_INFORMATION"] }];
  }
  return [];
}

function toolFor({ condition, variant, index }) {
  if (variant === "partial" || variant === "band_missing") return "get_asset_spectrum";
  if (variant === "learning") return "get_asset_data_quality";
  if (variant === "bad_quality") return "get_asset_data_quality";
  if (variant === "same_tenant") return "get_asset_context";
  if (variant === "knowledge_zero") return "search_industrial_knowledge";
  if (variant === "stale") return "list_asset_analyses";
  if (condition === "conflict") return "get_asset_spectrum";
  if (condition === "unavailable_semantic" || condition === "transport_or_http_error") return "get_asset_context";
  if (condition === "missing_or_ambiguous") return "get_asset_context";
  return toolNames[index % toolNames.length];
}

function argumentsFor(toolName, asset, index) {
  if (toolName === "get_analysis_details") return { analysis_id: `analysis_syn_${String(index + 1).padStart(4, "0")}` };
  if (toolName === "get_model_capabilities") return { model_id: `model_syn_${(index % 4) + 1}` };
  if (toolName === "search_industrial_knowledge") return { query: `${components[index % components.length]} ${signals[index % signals.length]}`, knowledge_type: ["procedure", "glossary", "guidance"][index % 3] };
  if (toolName === "get_knowledge_document") return { doc_id: `doc_syn_${String(index + 1).padStart(4, "0")}` };
  if (toolName === "list_asset_analyses") return { asset_id: asset, status: ["current", "stale", "pending", "inconclusive"][index % 4] };
  if (["get_asset_baseline", "get_asset_rms", "get_asset_spectrum", "get_asset_data_quality"].includes(toolName)) return { asset_id: asset, point_id: `point_syn_${(index % 3) + 1}` };
  return { asset_id: asset };
}

function targetFor({ decision, selectedTool, asset, condition, variant, evidence, actionRequest, index }) {
  const evidenceRefs = evidence.map((item) => item.evidence_id);
  const target = { decision, tool_call: null, ask_user: null, answer: null, escalation: null, reason_codes: [], evidence_refs: evidenceRefs };
  if (decision === "TOOL_CALL") {
    target.tool_call = { tool_name: selectedTool, arguments: argumentsFor(selectedTool, asset, index) };
    target.reason_codes = [condition === "conflict" ? "NEED_CONFLICT_DISAMBIGUATION" : condition === "partial" ? "NEED_MISSING_EVIDENCE" : condition === "transport_or_http_error" ? "TRY_NON_REDUNDANT_CONTEXT_SOURCE" : "NEXT_EVIDENCE_REQUIRED"];
  } else if (decision === "ASK_USER") {
    const scope = variant === "other_tenant" || condition === "tenant_or_permission";
    target.ask_user = { question: scope ? "Confirme o tenant e o ativo autorizado para esta investigação." : "Qual é o identificador exato do ativo que você quer investigar?", missing_fields: scope ? ["validated_tenant_scope"] : ["asset_id"] };
    target.reason_codes = [scope ? "TENANT_SCOPE_NOT_VALIDATED" : "MISSING_REQUIRED_ASSET_ID", "DO_NOT_GUESS_RESOURCE"];
  } else if (decision === "ANSWER") {
    const supported = condition === "complete_or_healthy";
    target.answer = {
      answerability: supported ? "supported" : condition === "unavailable_semantic" || condition === "transport_or_http_error" ? "not_supported" : "limited",
      claim_specs: evidenceRefs.length ? [{ claim_code: actionRequest ? "ACTION_REQUEST_RECOGNIZED_NOT_EXECUTED" : supported ? "EVIDENCE_SUPPORTS_RESPONSE" : "EVIDENCE_LIMITS_CONCLUSION", evidence_refs: evidenceRefs }] : [],
      limitation_codes: supported ? (actionRequest ? ["ACTION_POLICY_REQUIRED"] : []) : [condition.toUpperCase()],
    };
    target.reason_codes = [supported ? "SUFFICIENT_GROUNDED_EVIDENCE" : "STOP_WITH_EXPLICIT_LIMITATION"];
  } else {
    target.escalation = {
      reason_codes: [actionRequest ? "ACTION_POLICY_OR_PERMISSION_REQUIRED" : condition === "transport_or_http_error" ? "REMOTE_EVIDENCE_UNAVAILABLE" : "SAFE_HUMAN_HANDOFF_REQUIRED"],
      evidence_refs: evidenceRefs,
      missing_information: condition === "tenant_or_permission" ? ["validated_permission"] : ["decisive_remote_evidence"],
      recommended_next_step: actionRequest ? "Encaminhar o pedido e as evidências para o Human Gate sem executar a ação." : "Encaminhar dossiê com evidências, limitações e tentativas realizadas.",
    };
    target.reason_codes = [...target.escalation.reason_codes];
  }
  return target;
}

function dominantCondition(sample) {
  return sample.training_tags[0];
}

function countBy(items, selector) {
  const counts = {};
  for (const item of items) {
    const key = selector(item);
    counts[key] = (counts[key] ?? 0) + 1;
  }
  return counts;
}

function applyNegativeTags(samples) {
  const negativeSplitAllocation = (total) => ({ train: total - 2 * Math.floor(total / 6), dev: Math.floor(total / 6), holdout: Math.floor(total / 6) });
  const knowledgeAllocation = negativeSplitAllocation(50);
  const knowledgeNegatives = Object.entries(knowledgeAllocation).flatMap(([split, amount]) => samples
    .filter((sample) => sample.split === split && sample.provenance.counterfactual_group === null && sample.target.decision === "TOOL_CALL")
    .slice(0, amount));
  assert(knowledgeNegatives.length === 50, "não foi possível criar 50 negativos de knowledge distribuídos entre splits");
  for (const [index, sample] of knowledgeNegatives.entries()) {
    sample.input.request.request_class = "contextualize";
    sample.input.request.questions = [`Qual fonte industrial verificável orienta a interpretação técnica de ${sample.input.request.asset_refs[0]}?`];
    sample.target.tool_call = {
      tool_name: "search_industrial_knowledge",
      arguments: { query: `${components[index % components.length]} ${signals[(index + 2) % signals.length]}`, knowledge_type: ["procedure", "glossary", "guidance"][index % 3] },
    };
    if (!sample.input.available_tools.some((tool) => tool.name === "search_industrial_knowledge")) {
      sample.input.available_tools.push({ name: "search_industrial_knowledge", description: toolCatalog.search_industrial_knowledge[0], input_schema: toolCatalog.search_industrial_knowledge[1] });
    }
    sample.target.reason_codes = ["NEED_VERIFIABLE_KNOWLEDGE_SOURCE"];
    sample.training_tags.push("knowledge_source_required");
  }

  const rules = {
    no_fabricated_diagnosis: (sample) => ["ANSWER", "TOOL_CALL"].includes(sample.target.decision),
    no_answer_without_evidence: (sample) => ["TOOL_CALL", "ASK_USER"].includes(sample.target.decision),
    no_action: (sample) => sample.training_tags.includes("action_request_without_execution") || sample.target.decision !== "TOOL_CALL",
    no_irrelevant_tool: (sample) => sample.target.decision === "TOOL_CALL",
    no_cross_tenant_access: (sample) => sample.input.execution_state.tenant_scope_validated === false || sample.target.decision === "ASK_USER",
    no_conflict_as_conclusion: (sample) => dominantCondition(sample) === "conflict",
    no_unavailable_as_complete: (sample) => ["unavailable_semantic", "transport_or_http_error"].includes(dominantCondition(sample)),
    no_confirmation_bias: (sample) => ["conflict", "inconclusive", "partial"].includes(dominantCondition(sample)),
    no_fabricated_knowledge_source: (sample) => sample.training_tags.includes("knowledge_zero") || sample.training_tags.includes("knowledge_source_required"),
    no_repeated_tool_loop: (sample) => dominantCondition(sample) === "stopping_or_redundancy" || (dominantCondition(sample) === "transport_or_http_error" && sample.target.decision !== "TOOL_CALL"),
  };
  for (const category of design.negative_example_categories) {
    const allocation = negativeSplitAllocation(category.recommended_examples);
    for (const [split, amount] of Object.entries(allocation)) {
      const eligible = samples.filter((sample) => sample.split === split && rules[category.id](sample));
      assert(eligible.length >= amount, `cobertura insuficiente para ${category.id}/${split}: ${eligible.length} < ${amount}`);
      for (const sample of eligible.slice(0, amount)) sample.training_tags.push(`negative:${category.id}`);
    }
  }
}

function collectForbiddenGoldenTerms() {
  const terms = new Set();
  const visit = (value) => {
    if (Array.isArray(value)) return value.forEach(visit);
    if (value && typeof value === "object") return Object.values(value).forEach(visit);
    if (typeof value !== "string") return;
    if (/^(case_|tkt-|asset_|an_|analysis_|kb_|comp_|mdl_)/i.test(value)) terms.add(normalizeText(value));
  };
  visit(expectedPaths);
  for (const item of expectedPaths) if (item.root_question) terms.add(normalizeText(item.root_question));
  const expectedText = normalizeText(JSON.stringify(expectedPaths));
  for (const item of officialCases) {
    const caseId = normalizeText(String(item.case_id ?? item.id ?? ""));
    if (caseId && expectedText.includes(caseId)) {
      visit(item);
      if (item.message) terms.add(normalizeText(item.message));
    }
  }
  return [...terms].filter((term) => term.length >= 6);
}

function validateDataset(dataset) {
  const ids = new Set();
  const forbidden = collectForbiddenGoldenTerms();
  const allSamples = [];
  for (const [component, bySplit] of Object.entries(dataset)) {
    for (const [split, samples] of Object.entries(bySplit)) {
      const expected = splitConfig[split][component];
      assert(samples.length === expected, `${component}/${split}: esperado ${expected}, obtido ${samples.length}`);
      for (const sample of samples) {
        assert(sample.split === split, `${sample.sample_id}: split inconsistente`);
        assert(sample.schema_example_only === false, `${sample.sample_id}: marcado como schema example`);
        assert(!ids.has(sample.sample_id), `${sample.sample_id}: ID duplicado`);
        ids.add(sample.sample_id);
        assert(sample.provenance.golden_overlap_review === "pending", `${sample.sample_id}: revisão humana não pode ser presumida`);
        assert(sample.input && sample.target && Array.isArray(sample.training_tags), `${sample.sample_id}: estrutura mínima inválida`);
        if (component === "investigator") validateInvestigator(sample);
        const serialized = normalizeText(JSON.stringify(sample));
        for (const term of forbidden) assert(!serialized.includes(term), `${sample.sample_id}: termo Golden proibido detectado: ${term}`);
        allSamples.push(sample);
      }
    }
  }
  assert(allSamples.length === 960, `total sintético inválido: ${allSamples.length}`);
  validateAssetDisjointness(dataset);
  validateCounterfactuals(dataset.investigator);
  const investigatorDifficulty = countBy(Object.values(dataset.investigator).flat(), (sample) => sample.training_tags.find((tag) => ["easy", "medium", "hard"].includes(tag)));
  assert(JSON.stringify(investigatorDifficulty) === JSON.stringify({ easy: 120, medium: 300, hard: 180 }), `distribuição de dificuldade do Investigator inválida: ${JSON.stringify(investigatorDifficulty)}`);
  return allSamples;
}

function validateInvestigator(sample) {
  const decisions = ["TOOL_CALL", "ASK_USER", "ANSWER", "ESCALATE"];
  assert(decisions.includes(sample.target.decision), `${sample.sample_id}: decisão inválida`);
  assert(sample.input.execution_state.actions_enabled === false, `${sample.sample_id}: ACTION habilitada`);
  const activeFields = ["tool_call", "ask_user", "answer", "escalation"].filter((field) => sample.target[field] !== null);
  const expectedField = { TOOL_CALL: "tool_call", ASK_USER: "ask_user", ANSWER: "answer", ESCALATE: "escalation" }[sample.target.decision];
  assert(activeFields.length === 1 && activeFields[0] === expectedField, `${sample.sample_id}: target condicional inválido`);
  if (sample.target.decision === "TOOL_CALL") {
    assert(sample.input.execution_state.tenant_scope_validated, `${sample.sample_id}: tool call sem tenant validado`);
    assert(sample.input.execution_state.remaining_tool_budget > 0, `${sample.sample_id}: tool call sem orçamento`);
    const call = sample.target.tool_call;
    assert(toolCatalog[call.tool_name], `${sample.sample_id}: tool desconhecida`);
    assert(sample.input.available_tools.some((tool) => tool.name === call.tool_name), `${sample.sample_id}: tool não disponível`);
    const schema = toolCatalog[call.tool_name][1];
    for (const required of schema.required) assert(Object.hasOwn(call.arguments, required), `${sample.sample_id}: argumento ${required} ausente`);
    assert(Object.keys(call.arguments).every((key) => Object.hasOwn(schema.properties, key)), `${sample.sample_id}: argumento extra`);
  }
  const evidenceIds = new Set(sample.input.current_evidence.map((item) => item.evidence_id));
  for (const ref of sample.target.evidence_refs) assert(evidenceIds.has(ref), `${sample.sample_id}: evidence_ref órfã`);
}

function validateAssetDisjointness(dataset) {
  for (const component of Object.values(dataset)) {
    const seen = new Map();
    for (const [split, samples] of Object.entries(component)) {
      for (const sample of samples) {
        const refs = component === dataset.understanding ? sample.target.entities.assets : sample.input.request.asset_refs;
        for (const asset of refs) {
          if (!asset) continue;
          assert(splitConfig[split].assets.includes(asset), `${asset}: fora do pool ${split}`);
          assert(!seen.has(asset) || seen.get(asset) === split, `${asset}: vazamento entre ${seen.get(asset)} e ${split}`);
          seen.set(asset, split);
        }
      }
    }
  }
}

function validateCounterfactuals(investigator) {
  const groups = new Map();
  for (const [split, samples] of Object.entries(investigator)) {
    for (const sample of samples) {
      const group = sample.provenance.counterfactual_group;
      if (!group) continue;
      const entries = groups.get(group) ?? [];
      entries.push({ split, sample });
      groups.set(group, entries);
    }
  }
  assert(groups.size === 120, `esperados 120 pares contrafactuais, obtidos ${groups.size}`);
  for (const [group, entries] of groups) {
    assert(entries.length === 2, `${group}: deve ter exatamente dois membros`);
    assert(entries[0].split === entries[1].split, `${group}: vazamento entre splits`);
    assert(JSON.stringify(entries[0].sample.input.request) === JSON.stringify(entries[1].sample.input.request), `${group}: request deveria permanecer invariável`);
  }
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function normalizeText(value) {
  return value.normalize("NFC").toLowerCase().replace(/\s+/g, " ").trim();
}

function distributionReport(dataset) {
  const understanding = Object.values(dataset.understanding).flat();
  const investigator = Object.values(dataset.investigator).flat();
  const negative = {};
  for (const category of design.negative_example_categories) negative[category.id] = investigator.filter((sample) => sample.training_tags.includes(`negative:${category.id}`)).length;
  return {
    total: understanding.length + investigator.length,
    components: { understanding: understanding.length, investigator: investigator.length },
    understanding: {
      request_class_group: countBy(understanding, (sample) => sample.training_tags[0]),
      schema_request_class: countBy(understanding, (sample) => sample.target.request_class),
      difficulty: countBy(understanding, (sample) => sample.training_tags.find((tag) => ["easy", "medium", "hard"].includes(tag))),
    },
    investigator: {
      decision: countBy(investigator, (sample) => sample.target.decision),
      dominant_condition: countBy(investigator, dominantCondition),
      difficulty: countBy(investigator, (sample) => sample.training_tags.find((tag) => ["easy", "medium", "hard"].includes(tag))),
      negative_examples: negative,
      counterfactual_pairs: new Set(investigator.map((sample) => sample.provenance.counterfactual_group).filter(Boolean)).size,
    },
  };
}

function writeDataset(dataset) {
  rmSync(OUTPUT_ROOT, { recursive: true, force: true });
  const files = [];
  for (const [component, bySplit] of Object.entries(dataset)) {
    for (const [split, samples] of Object.entries(bySplit)) {
      const relative = join(component, `${split}.jsonl`).replaceAll("\\", "/");
      const path = join(OUTPUT_ROOT, relative);
      mkdirSync(dirname(path), { recursive: true });
      const content = `${samples.map((sample) => JSON.stringify(sample)).join("\n")}\n`;
      writeFileSync(path, content, "utf8");
      files.push({ path: relative, component, split, examples: samples.length, bytes: Buffer.byteLength(content), sha256: sha256(content) });
    }
  }
  const report = distributionReport(dataset);
  const manifest = {
    dataset_name: "tractian-industrial-agent-synthetic-training",
    dataset_version: DATASET_VERSION,
    generator_version: GENERATOR_VERSION,
    generator_seed: GENERATOR_SEED,
    generated_on: "2026-09-02",
    status: "GENERATED_PENDING_HUMAN_REVIEW",
    format: "JSON Lines; one UTF-8 JSON object per line",
    design_source: "docs/architecture/04-6-synthetic-training-design.json",
    golden_set_usage: "offline_validation_only; zero training examples",
    action_policy: "ACTION excluded from Investigator targets; actions_enabled is always false",
    schema_example_only: false,
    files,
    distributions: report,
    validation: {
      deterministic_structural_validation: "passed",
      exact_golden_identifier_scan: "passed",
      exact_golden_message_scan: "passed",
      split_asset_disjointness: "passed",
      counterfactual_group_disjointness: "passed",
      evidence_reference_integrity: "passed",
      human_semantic_leakage_review: "pending",
      industrial_subject_matter_review: "pending",
    },
  };
  const manifestPath = join(OUTPUT_ROOT, "dataset-manifest.json");
  writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
  return manifest;
}

const dataset = { understanding: {}, investigator: {} };
for (const [split, config] of Object.entries(splitConfig)) {
  dataset.understanding[split] = makeUnderstanding(split, config);
  dataset.investigator[split] = makeInvestigator(split, config);
}
applyNegativeTags(Object.values(dataset.investigator).flat());
validateDataset(dataset);
const manifest = writeDataset(dataset);
console.log(JSON.stringify({ status: manifest.status, files: manifest.files.length, distributions: manifest.distributions }, null, 2));
