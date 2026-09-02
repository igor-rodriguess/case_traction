import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const DATASET_ROOT = join(ROOT, "datasets", "synthetic");
const manifest = readJson(join(DATASET_ROOT, "dataset-manifest.json"));
const design = readJson(join(ROOT, "docs", "architecture", "04-6-synthetic-training-design.json"));
const expectedPaths = readJson(join(ROOT, "eval", "expected-paths.json"));
const officialCases = readJson(join(ROOT, "agent-input", "cases.json"));
const schemas = { understanding: design.understanding_schema, investigator: design.investigator_schema };
const readTools = ["get_asset_context", "list_asset_analyses", "get_analysis_details", "get_asset_baseline", "get_asset_rms", "get_asset_spectrum", "get_asset_data_quality", "get_model_capabilities", "search_industrial_knowledge", "get_knowledge_document"];
const samples = { understanding: {}, investigator: {} };
const ids = new Set();
const errors = [];

for (const file of manifest.files) {
  const path = join(DATASET_ROOT, file.path);
  const content = readFileSync(path, "utf8");
  check(hash(content) === file.sha256, `${file.path}: SHA-256 divergente`);
  check(Buffer.byteLength(content) === file.bytes, `${file.path}: tamanho divergente`);
  const records = content.trimEnd().split("\n").map((line, index) => {
    try {
      return JSON.parse(line);
    } catch (error) {
      errors.push(`${file.path}:${index + 1}: JSON inválido: ${error.message}`);
      return null;
    }
  }).filter(Boolean);
  check(records.length === file.examples, `${file.path}: contagem divergente`);
  samples[file.component][file.split] = records;
  for (const [index, sample] of records.entries()) {
    validateSchema(schemas[file.component], sample, `${file.path}:${index + 1}`, errors);
    check(sample.schema_example_only === false, `${sample.sample_id}: schema_example_only deve ser false`);
    check(!ids.has(sample.sample_id), `${sample.sample_id}: ID duplicado`);
    ids.add(sample.sample_id);
  }
}

const allUnderstanding = Object.values(samples.understanding).flat();
const allInvestigator = Object.values(samples.investigator).flat();
check(allUnderstanding.length === 360, `Understanding: esperado 360, obtido ${allUnderstanding.length}`);
check(allInvestigator.length === 600, `Investigator: esperado 600, obtido ${allInvestigator.length}`);
check(ids.size === 960, `IDs únicos: esperado 960, obtido ${ids.size}`);
check(new Set(allUnderstanding.map((sample) => sample.input.message)).size === allUnderstanding.length, "Understanding contém mensagens exatamente duplicadas");
check(new Set(allInvestigator.map((sample) => JSON.stringify(sample.input))).size === allInvestigator.length, "Investigator contém inputs exatamente duplicados");
for (const sample of allUnderstanding) {
  if (sample.target.missing_information.some((item) => item.field === "asset_id" && item.blocking)) {
    check(sample.input.available_context.asset_refs.length === 0, `${sample.sample_id}: asset ambíguo apareceu no contexto`);
    check(sample.target.entities.assets.length === 0, `${sample.sample_id}: target inferiu asset ausente`);
    check(sample.target.intents.every((intent) => intent.target_entities.length === 0), `${sample.sample_id}: intent inferiu asset ausente`);
  }
}

const expectedDecisions = { TOOL_CALL: 330, ASK_USER: 90, ANSWER: 120, ESCALATE: 60 };
const expectedConditions = { complete_or_healthy: 120, partial: 80, inconclusive: 70, conflict: 70, unavailable_semantic: 60, transport_or_http_error: 60, missing_or_ambiguous: 50, tenant_or_permission: 50, stopping_or_redundancy: 40 };
const expectedUnderstanding = { contextualize: 90, investigate: 150, execute_or_handoff_recognition: 80, mixed_or_unclear: 40 };
checkSame(countBy(allInvestigator, (sample) => sample.target.decision), expectedDecisions, "decisões Investigator");
checkSame(countBy(allInvestigator, (sample) => sample.training_tags[0]), expectedConditions, "condições Investigator");
checkSame(countBy(allUnderstanding, (sample) => sample.training_tags[0]), expectedUnderstanding, "grupos de classe Understanding");
checkSame(countDifficulty(allUnderstanding), { easy: 126, medium: 162, hard: 72 }, "dificuldade Understanding");
checkSame(countDifficulty(allInvestigator), { easy: 120, medium: 300, hard: 180 }, "dificuldade Investigator");

for (const sample of allInvestigator) {
  check(sample.input.execution_state.actions_enabled === false, `${sample.sample_id}: actions_enabled não é false`);
  check(sample.target.decision !== "ACTION", `${sample.sample_id}: ACTION proibida`);
  const evidenceIds = new Set(sample.input.current_evidence.map((item) => item.evidence_id));
  for (const ref of sample.target.evidence_refs) check(evidenceIds.has(ref), `${sample.sample_id}: evidence_ref órfã ${ref}`);
  if (sample.target.decision === "TOOL_CALL") {
    check(sample.input.execution_state.tenant_scope_validated, `${sample.sample_id}: tool call cross-tenant`);
    check(sample.input.execution_state.remaining_tool_budget > 0, `${sample.sample_id}: tool call sem budget`);
    check(sample.input.available_tools.some((tool) => tool.name === sample.target.tool_call.tool_name), `${sample.sample_id}: tool indisponível`);
  }
}
for (const [split, records] of Object.entries(samples.investigator)) {
  const usedTools = new Set(records.filter((sample) => sample.target.decision === "TOOL_CALL").map((sample) => sample.target.tool_call.tool_name));
  for (const tool of readTools) check(usedTools.has(tool), `${split}: READ tool sem cobertura em TOOL_CALL: ${tool}`);
}

validatePools(samples);
validateCounterfactuals(allInvestigator);
validateNegativeCoverage(allInvestigator);
scanGoldenLeakage([...allUnderstanding, ...allInvestigator]);

if (errors.length) {
  console.error(errors.slice(0, 100).join("\n"));
  console.error(`VALIDATION_FAILED: ${errors.length} erro(s)`);
  process.exit(1);
}

console.log(JSON.stringify({
  status: "VALIDATED_PENDING_HUMAN_REVIEW",
  files: manifest.files.length,
  examples: ids.size,
  understanding: allUnderstanding.length,
  investigator: allInvestigator.length,
  counterfactual_pairs: new Set(allInvestigator.map((sample) => sample.provenance.counterfactual_group).filter(Boolean)).size,
  action_targets: allInvestigator.filter((sample) => sample.target.decision === "ACTION").length,
  exact_golden_leaks: 0,
  human_semantic_review: "pending",
}, null, 2));

function readJson(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}

function hash(content) {
  return createHash("sha256").update(content).digest("hex");
}

function check(condition, message) {
  if (!condition) errors.push(message);
}

function checkSame(actual, expected, label) {
  for (const [key, count] of Object.entries(expected)) check(actual[key] === count, `${label}/${key}: esperado ${count}, obtido ${actual[key] ?? 0}`);
  for (const key of Object.keys(actual)) check(Object.hasOwn(expected, key), `${label}: categoria inesperada ${key}`);
}

function countBy(items, selector) {
  const result = {};
  for (const item of items) {
    const key = selector(item);
    result[key] = (result[key] ?? 0) + 1;
  }
  return result;
}

function countDifficulty(items) {
  return countBy(items, (sample) => sample.training_tags.find((tag) => ["easy", "medium", "hard"].includes(tag)) ?? "missing");
}

function validatePools(dataset) {
  const pools = Object.fromEntries(Object.entries(design.dataset_splits).filter(([key]) => key.startsWith("synthetic/")).map(([key, value]) => [key.split("/")[1], new Set(value.asset_pool)]));
  for (const [component, bySplit] of Object.entries(dataset)) {
    const ownership = new Map();
    for (const [split, records] of Object.entries(bySplit)) {
      for (const sample of records) {
        const refs = component === "understanding" ? sample.target.entities.assets : sample.input.request.asset_refs;
        for (const asset of refs) {
          check(pools[split].has(asset), `${sample.sample_id}: ${asset} fora do pool ${split}`);
          check(!ownership.has(asset) || ownership.get(asset) === split, `${sample.sample_id}: ${asset} aparece em dois splits`);
          ownership.set(asset, split);
        }
      }
    }
  }
}

function validateCounterfactuals(records) {
  const groups = new Map();
  for (const sample of records) {
    const group = sample.provenance.counterfactual_group;
    if (!group) continue;
    groups.set(group, [...(groups.get(group) ?? []), sample]);
  }
  check(groups.size === 120, `pares contrafactuais: esperado 120, obtido ${groups.size}`);
  for (const [group, members] of groups) {
    check(members.length === 2, `${group}: esperado par, obtido ${members.length}`);
    if (members.length !== 2) continue;
    check(members[0].split === members[1].split, `${group}: membros em splits diferentes`);
    check(JSON.stringify(members[0].input.request) === JSON.stringify(members[1].input.request), `${group}: request não permaneceu invariável`);
    check(members[0].training_tags[2] !== members[1].training_tags[2], `${group}: variável contrafactual não mudou`);
  }
}

function validateNegativeCoverage(records) {
  for (const category of design.negative_example_categories) {
    const count = records.filter((sample) => sample.training_tags.includes(`negative:${category.id}`)).length;
    check(count === category.recommended_examples, `${category.id}: esperado ${category.recommended_examples}, obtido ${count}`);
    const perSplit = { train: category.recommended_examples - 2 * Math.floor(category.recommended_examples / 6), dev: Math.floor(category.recommended_examples / 6), holdout: Math.floor(category.recommended_examples / 6) };
    for (const [split, expected] of Object.entries(perSplit)) {
      const actual = records.filter((sample) => sample.split === split && sample.training_tags.includes(`negative:${category.id}`)).length;
      check(actual === expected, `${category.id}/${split}: esperado ${expected}, obtido ${actual}`);
    }
  }
}

function scanGoldenLeakage(records) {
  const terms = new Set();
  const visit = (value) => {
    if (Array.isArray(value)) return value.forEach(visit);
    if (value && typeof value === "object") return Object.values(value).forEach(visit);
    if (typeof value === "string" && /^(case_|tkt-|asset_|an_|analysis_|kb_|comp_|mdl_)/i.test(value) && value.length >= 6) terms.add(normalizeText(value));
  };
  visit(expectedPaths);
  for (const item of expectedPaths) if (item.root_question) terms.add(normalizeText(item.root_question));
  const expectedText = normalizeText(JSON.stringify(expectedPaths));
  for (const item of officialCases) {
    const id = normalizeText(String(item.case_id ?? item.id ?? ""));
    if (id && expectedText.includes(id)) {
      visit(item);
      if (item.message) terms.add(normalizeText(item.message));
    }
  }
  for (const sample of records) {
    const text = normalizeText(JSON.stringify(sample));
    for (const term of terms) check(!text.includes(term), `${sample.sample_id}: referência Golden exata detectada: ${term}`);
  }
}

function normalizeText(value) {
  return value.normalize("NFC").toLowerCase().replace(/\s+/g, " ").trim();
}

function validateSchema(schema, value, path, targetErrors) {
  const local = schemaErrors(schema, value, path);
  targetErrors.push(...local);
}

function schemaErrors(schema, value, path) {
  const found = [];
  const fail = (message) => found.push(`${path}: ${message}`);
  if (Object.hasOwn(schema, "const") && !deepEqual(value, schema.const)) fail(`valor diferente de const ${JSON.stringify(schema.const)}`);
  if (schema.enum && !schema.enum.some((item) => deepEqual(item, value))) fail(`valor fora do enum`);
  if (schema.oneOf) {
    const matches = schema.oneOf.filter((branch) => schemaErrors(branch, value, path).length === 0).length;
    if (matches !== 1) fail(`oneOf exige uma alternativa válida; obtidas ${matches}`);
  }
  if (schema.allOf) for (const branch of schema.allOf) found.push(...schemaErrors(branch, value, path));
  if (schema.if && schemaErrors(schema.if, value, path).length === 0 && schema.then) found.push(...schemaErrors(schema.then, value, path));
  if (schema.type && !matchesType(schema.type, value)) {
    fail(`tipo inválido; esperado ${JSON.stringify(schema.type)}, obtido ${value === null ? "null" : Array.isArray(value) ? "array" : typeof value}`);
    return found;
  }
  if (typeof value === "string") {
    if (schema.pattern && !new RegExp(schema.pattern).test(value)) fail(`string não corresponde ao pattern`);
  }
  if (typeof value === "number") {
    if (schema.minimum !== undefined && value < schema.minimum) fail(`menor que minimum`);
    if (schema.maximum !== undefined && value > schema.maximum) fail(`maior que maximum`);
  }
  if (Array.isArray(value)) {
    if (schema.minItems !== undefined && value.length < schema.minItems) fail(`menos itens que minItems`);
    if (schema.uniqueItems && new Set(value.map(JSON.stringify)).size !== value.length) fail(`itens não únicos`);
    if (schema.items) value.forEach((item, index) => found.push(...schemaErrors(schema.items, item, `${path}[${index}]`)));
  }
  if (value && typeof value === "object" && !Array.isArray(value)) {
    for (const required of schema.required ?? []) if (!Object.hasOwn(value, required)) fail(`campo obrigatório ausente: ${required}`);
    if (schema.additionalProperties === false && schema.properties) for (const key of Object.keys(value)) if (!Object.hasOwn(schema.properties, key)) fail(`campo extra: ${key}`);
    for (const [key, childSchema] of Object.entries(schema.properties ?? {})) if (Object.hasOwn(value, key)) found.push(...schemaErrors(childSchema, value[key], `${path}.${key}`));
  }
  return found;
}

function matchesType(type, value) {
  const types = Array.isArray(type) ? type : [type];
  return types.some((candidate) => {
    if (candidate === "null") return value === null;
    if (candidate === "array") return Array.isArray(value);
    if (candidate === "object") return value !== null && typeof value === "object" && !Array.isArray(value);
    if (candidate === "integer") return Number.isInteger(value);
    if (candidate === "number") return typeof value === "number" && Number.isFinite(value);
    return typeof value === candidate;
  });
}

function deepEqual(left, right) {
  return JSON.stringify(left) === JSON.stringify(right);
}
