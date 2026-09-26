/**
 * A tiny JSON Schema checker for the OpenAPI 3.1 schemas FastAPI/pydantic emit (tests only):
 * `$ref` (to `#/components/schemas/…`), `type` (incl. arrays of types), `enum`, `const`, `anyOf`,
 * `oneOf`, `allOf`, `properties`/`required`/`additionalProperties`, `items`, `prefixItems`,
 * `minimum`/`maximum`, `minLength`/`maxLength`, `minItems`/`maxItems` and `pattern`.
 *
 * `strict` also reports properties an object schema does not declare (pydantic response models
 * never add any, so a mock that does has drifted from the API).
 */
export type Schema = Record<string, unknown>;

export interface OpenApiDoc {
  paths: Record<string, Record<string, Operation>>;
  components: { schemas: Record<string, Schema> };
}

export interface Parameter {
  name: string;
  in: "query" | "path" | "header" | "cookie";
  required?: boolean;
  schema: Schema;
}

export interface Operation {
  parameters?: Parameter[];
  requestBody?: { content: Record<string, { schema: Schema }> };
  responses: Record<string, { content?: Record<string, { schema?: Schema }> }>;
}

const REF = "#/components/schemas/";

function typeOf(value: unknown): string {
  if (value === null) return "null";
  if (Array.isArray(value)) return "array";
  if (typeof value === "number") return Number.isInteger(value) ? "integer" : "number";
  return typeof value;
}

function typeMatches(expected: string, actual: string): boolean {
  return expected === actual || (expected === "number" && actual === "integer");
}

export class SchemaChecker {
  constructor(
    private readonly doc: OpenApiDoc,
    private readonly strict = false,
  ) {}

  /** Human-readable problems of `value` against `schema` (empty when it conforms). */
  check(value: unknown, schema: Schema, path = "$"): string[] {
    const errors: string[] = [];
    this.walk(value, schema, path, errors);
    return errors;
  }

  resolve(schema: Schema): Schema {
    const ref = schema.$ref;
    if (typeof ref !== "string") return schema;
    if (!ref.startsWith(REF)) throw new Error(`unsupported $ref ${ref}`);
    const target = this.doc.components.schemas[ref.slice(REF.length)];
    if (!target) throw new Error(`unknown schema ${ref}`);
    return this.resolve(target);
  }

  private walk(value: unknown, raw: Schema, path: string, errors: string[]): void {
    const schema = this.resolve(raw);
    const actual = typeOf(value);

    if (Array.isArray(schema.allOf)) for (const part of schema.allOf as Schema[]) this.walk(value, part, path, errors);
    for (const key of ["anyOf", "oneOf"] as const) {
      const options = schema[key];
      if (!Array.isArray(options)) continue;
      const results = (options as Schema[]).map((option) => this.check(value, option, path));
      const passing = results.filter((r) => r.length === 0).length;
      if (passing === 0) {
        // report the closest option's problems (fewest errors), which is usually the intended one
        const closest = results.reduce((a, b) => (b.length < a.length ? b : a));
        errors.push(...(closest.length ? closest : [`${path}: matches none of ${key}`]));
      } else if (key === "oneOf" && passing > 1) errors.push(`${path}: matches ${passing} oneOf options`);
    }

    if ("const" in schema && value !== schema.const) errors.push(`${path}: expected ${JSON.stringify(schema.const)}, got ${JSON.stringify(value)}`);
    if (Array.isArray(schema.enum) && !schema.enum.includes(value)) errors.push(`${path}: ${JSON.stringify(value)} is not one of ${JSON.stringify(schema.enum)}`);

    const types = schema.type === undefined ? null : Array.isArray(schema.type) ? (schema.type as string[]) : [schema.type as string];
    if (types && !types.some((t) => typeMatches(t, actual))) {
      errors.push(`${path}: expected ${types.join(" | ")}, got ${actual} (${JSON.stringify(value)?.slice(0, 80)})`);
      return;
    }

    if (actual === "number" || actual === "integer") {
      const n = value as number;
      if (typeof schema.minimum === "number" && n < schema.minimum) errors.push(`${path}: ${n} < minimum ${schema.minimum}`);
      if (typeof schema.maximum === "number" && n > schema.maximum) errors.push(`${path}: ${n} > maximum ${schema.maximum}`);
      if (typeof schema.exclusiveMinimum === "number" && n <= schema.exclusiveMinimum) errors.push(`${path}: ${n} <= ${schema.exclusiveMinimum}`);
      if (typeof schema.exclusiveMaximum === "number" && n >= schema.exclusiveMaximum) errors.push(`${path}: ${n} >= ${schema.exclusiveMaximum}`);
    }
    if (actual === "string") {
      const s = value as string;
      if (typeof schema.minLength === "number" && s.length < schema.minLength) errors.push(`${path}: shorter than ${schema.minLength}`);
      if (typeof schema.maxLength === "number" && s.length > schema.maxLength) errors.push(`${path}: longer than ${schema.maxLength}`);
      if (typeof schema.pattern === "string" && !new RegExp(schema.pattern, "u").test(s)) errors.push(`${path}: ${JSON.stringify(s)} does not match ${schema.pattern}`);
    }
    if (actual === "array") {
      const items = value as unknown[];
      if (typeof schema.minItems === "number" && items.length < schema.minItems) errors.push(`${path}: fewer than ${schema.minItems} items`);
      if (typeof schema.maxItems === "number" && items.length > schema.maxItems) errors.push(`${path}: more than ${schema.maxItems} items`);
      const prefix = Array.isArray(schema.prefixItems) ? (schema.prefixItems as Schema[]) : [];
      items.forEach((item, i) => {
        const itemSchema = prefix[i] ?? (schema.items as Schema | undefined);
        if (itemSchema && typeof itemSchema === "object") this.walk(item, itemSchema, `${path}[${i}]`, errors);
      });
    }
    if (actual === "object") this.walkObject(value as Record<string, unknown>, schema, path, errors);
  }

  private walkObject(value: Record<string, unknown>, schema: Schema, path: string, errors: string[]): void {
    const properties = (schema.properties ?? {}) as Record<string, Schema>;
    for (const name of (schema.required ?? []) as string[]) {
      if (!(name in value)) errors.push(`${path}: missing required “${name}”`);
    }
    const extra = schema.additionalProperties;
    for (const [name, item] of Object.entries(value)) {
      const where = `${path}.${name}`;
      if (name in properties) this.walk(item, properties[name]!, where, errors);
      else if (extra && typeof extra === "object") this.walk(item, extra as Schema, where, errors);
      else if (extra === false || (this.strict && extra === undefined && schema.properties !== undefined)) {
        errors.push(`${where}: not declared by the API`);
      }
    }
  }
}
