import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  BEARER_VALUE_MIN_LENGTH,
  BEARER_VALUE_SHAPE,
  CREDENTIAL_WORD_PATTERNS,
  INTERNAL_STATE_PRIVATE_TEXT_PATTERNS,
  INTERNAL_STATE_SHAPE_PATTERNS,
  PRIVATE_TEXT_PATTERNS,
  VISION_REFRESH_REQUEST_SCHEMA,
  buildVisionCheckpoint,
} from "../../loopx/control_plane/goals/vision_checkpoint.ts";

// The Python owners (loopx/public_safe_text.py) and this TypeScript owner must
// agree on the same corpus. The Python parity test drives this file through
// refresh-state; this test pins the TypeScript owner on its own so the
// contract cannot drift when only the control-plane suite runs.
const CORPUS_PATH = fileURLToPath(
  new URL("../fixtures/public_safe_text_corpus.json", import.meta.url),
);

interface CorpusSample {
  id: string;
  template: string;
  note?: string;
}

interface Corpus {
  schema_version: string;
  tokens: Record<string, string[]>;
  public_safe: CorpusSample[];
  private_looking: CorpusSample[];
  internal_state_prose: CorpusSample[];
}

const corpus = JSON.parse(readFileSync(CORPUS_PATH, "utf8")) as Corpus;
assert.equal(corpus.schema_version, "public_safe_text_corpus_v1");

function render(template: string): string {
  return template.replace(/\{([A-Z][A-Z_]*)\}/g, (_match, name: string) => {
    const direct = corpus.tokens[name];
    if (direct !== undefined) return direct.join("");
    const lowerSuffix = "_LOWER";
    if (name.endsWith(lowerSuffix)) {
      const base = corpus.tokens[name.slice(0, -lowerSuffix.length)];
      if (base !== undefined) return base.join("").toLowerCase();
    }
    throw new Error(`corpus placeholder ${name} has no token definition`);
  });
}

function checkpoint(text: string): void {
  buildVisionCheckpoint({
    schema_version: VISION_REFRESH_REQUEST_SCHEMA,
    phase: "finalize",
    agent_id: "kiro-cli",
    agent_vision: null,
    existing_agent_vision: null,
    vision_unchanged_reason: text,
    delivery_outcome: "outcome_progress",
    active_state_next_action_would_update: false,
    delivery_boundary: null,
    todo_id: null,
    completion_todo_id: null,
    autonomous_replan_recorded: false,
  });
}

test("vision checkpoint accepts every public-safe corpus sample", () => {
  for (const sample of corpus.public_safe) {
    assert.doesNotThrow(() => checkpoint(render(sample.template)), sample.id);
  }
});

test("vision checkpoint rejects every private-looking corpus sample", () => {
  for (const sample of corpus.private_looking) {
    assert.throws(
      () => checkpoint(render(sample.template)),
      /private-looking value/,
      sample.id,
    );
  }
});

// Refs #5136, direction 2: this owner validates LoopX's own state, so a bare
// credential word is a fact about a credential rather than one. The Python tier
// test drives the same bucket through the three Python owners.
test("vision checkpoint accepts the internal-state prose corpus", () => {
  for (const sample of corpus.internal_state_prose) {
    assert.doesNotThrow(() => checkpoint(render(sample.template)), sample.id);
  }
});

test("the internal-state tier drops the words and adds the ported shapes", () => {
  // Without this, dropping a word arm and dropping a value arm would look the
  // same from the corpus alone. The composition is pinned, not the count.
  const wordSources = CREDENTIAL_WORD_PATTERNS.map((pattern) => pattern.source);
  assert.deepEqual(
    wordSources,
    [/\bBearer\b/i, /\bpassword\b/i, /\bsecret\b/i].map((pattern) => pattern.source),
  );
  assert.equal(INTERNAL_STATE_SHAPE_PATTERNS.length, 2);
  const expected = [
    ...PRIVATE_TEXT_PATTERNS.filter(
      (pattern) => !CREDENTIAL_WORD_PATTERNS.includes(pattern),
    ),
    ...INTERNAL_STATE_SHAPE_PATTERNS,
  ].map((pattern) => pattern.source);
  assert.deepEqual(
    INTERNAL_STATE_PRIVATE_TEXT_PATTERNS.map((pattern) => pattern.source),
    expected,
  );
});

test("the bearer floor is the named constant the pattern carries", () => {
  // BEARER_VALUE_SHAPE is a literal so the digest guard can fold it, which means
  // the constant has to be checked against the source rather than used to build it.
  const floor = new RegExp(`\\{${BEARER_VALUE_MIN_LENGTH},\\}`);
  assert.ok(floor.test(BEARER_VALUE_SHAPE.source), BEARER_VALUE_SHAPE.source);
  assert.ok(!BEARER_VALUE_SHAPE.test(`Bearer ${"a".repeat(BEARER_VALUE_MIN_LENGTH - 1)}`));
  assert.ok(BEARER_VALUE_SHAPE.test(`Bearer ${"a".repeat(BEARER_VALUE_MIN_LENGTH)}`));
});

test("the narrower tier still rejects every value and assignment shape", () => {
  // Each value below is one of the demoted words carrying something. Assembling
  // them keeps the fixture's discipline of carrying no literal credential text.
  const bearer = "Bear" + "er";
  const password = "pass" + "word";
  const secret = "sec" + "ret";
  const token = "tok" + "en";
  const rejected = [
    `${bearer} ${"a".repeat(8)}`,
    `${bearer} ${"a".repeat(40)}`,
    `${password}=hunter2`,
    `${secret}: env`,
    `${token}: abc123`,
    "/Us" + "ers/operator/state.json",
  ];
  for (const value of rejected) {
    assert.throws(
      () => checkpoint(value),
      /private-looking value/,
      `one char below/above floor: ${value.slice(0, 12)}`,
    );
  }
  const accepted = [
    `the ${bearer} token expired`,
    `the ${password} is stored in the vault`,
    `read the ${secret} from the environment`,
  ];
  for (const value of accepted) {
    assert.doesNotThrow(() => checkpoint(value), value.slice(0, 24));
  }
});
