// Copyright (c) 2024-2026 OpenConstruction Open Science Initiative
// SPDX-License-Identifier: Apache-2.0

import { CATALOGS, type CatalogKey } from "./registry.js";
import type { ClientOptions, DatasetDownloadPlan, RecordLike, SearchOptions } from "./types.js";

const DEFAULT_BASE = "https://www.openconstruction.org";

function joinUrl(base: string, path: string) {
  return `${base.replace(/\/+$/, "")}/${path.replace(/^\/+/, "")}`;
}

function normalizeToArray(raw: any): RecordLike[] {
  if (Array.isArray(raw)) return raw;

  // envelope: { datasets: [...] } or { models: [...] } etc.
  if (raw && typeof raw === "object") {
    for (const v of Object.values(raw)) {
      if (Array.isArray(v)) return v as RecordLike[];
    }
    // map: { ID: {...}, ... }
    return Object.values(raw) as RecordLike[];
  }
  return [];
}

function getByIdFromRaw(raw: any, id: string): RecordLike | null {
  if (raw && typeof raw === "object" && !Array.isArray(raw)) {
    const direct = raw[id];
    if (direct && typeof direct === "object") return direct as RecordLike;
  }
  const arr = normalizeToArray(raw);
  return arr.find(r => r?.id === id) ?? null;
}

function includesQuery(haystack: string, needle: string, caseSensitive: boolean) {
  return caseSensitive
    ? haystack.includes(needle)
    : haystack.toLowerCase().includes(needle.toLowerCase());
}

function isHttpUrl(value: unknown): value is string {
  if (typeof value !== "string" || !value.trim()) return false;
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

export class OpenConstructionClient {
  private baseUrl: string;
  private fetchImpl: typeof fetch;
  private noCache: boolean;

  constructor(opts: ClientOptions = {}) {
    this.baseUrl = opts.baseUrl ?? DEFAULT_BASE;
    this.fetchImpl = opts.fetchImpl ?? fetch;
    this.noCache = !!opts.noCache;
  }

  setBaseUrl(baseUrl: string) {
    this.baseUrl = baseUrl;
  }

  async fetchJSON<T = any>(path: string): Promise<T> {
    const url = joinUrl(this.baseUrl, path);
    const res = await this.fetchImpl(url, { cache: this.noCache ? "no-store" : "default" });
    if (!res.ok) throw new Error(`OpenConstruction fetch failed (${res.status}): ${url}`);
    return (await res.json()) as T;
  }

  /** Load raw catalog JSON */
  async catalog<T = any>(key: CatalogKey): Promise<T> {
    return this.fetchJSON<T>(CATALOGS[key]);
  }

  /** Normalize catalog to array (supports array, envelope, or map form) */
  async list(key: CatalogKey): Promise<RecordLike[]> {
    const raw = await this.catalog<any>(key);
    return normalizeToArray(raw);
  }

  /** Get record by ID (supports map + array forms) */
  async get(key: CatalogKey, id: string): Promise<RecordLike | null> {
    const raw = await this.catalog<any>(key);
    return getByIdFromRaw(raw, id);
  }

  /** Keyword search */
  async search(key: CatalogKey, query: string, opts: SearchOptions = {}): Promise<RecordLike[]> {
    const q = (query ?? "").trim();
    if (!q) return [];

    const limit = opts.limit ?? 200;
    const caseSensitive = !!opts.caseSensitive;
    const fields = opts.fields;

    const rows = await this.list(key);
    const out: RecordLike[] = [];

    for (const r of rows) {
      let blob: string;

      if (fields?.length) {
        blob = fields
          .map(f => r?.[f])
          .filter(v => v != null)
          .map(String)
          .join(" ");
      } else {
        blob = JSON.stringify(r);
      }

      if (includesQuery(blob, q, caseSensitive)) {
        out.push(r);
        if (out.length >= limit) break;
      }
    }
    return out;
  }

  /** Resolve the machine-readable retrieval strategy used by UI and MCP clients. */
  async datasetDownloadPlan(id: string): Promise<DatasetDownloadPlan | null> {
    const dataset = await this.get("datasets", id);
    if (!dataset) return null;

    const distributions = Array.isArray(dataset.distribution)
      ? dataset.distribution.filter((item: unknown) => item && typeof item === "object")
      : [];
    if (distributions.length === 1) {
      const distribution = distributions[0] as RecordLike;
      const url = distribution.content_url ?? distribution.contentUrl ?? distribution.url;
      if (distribution.browser_download !== false && isHttpUrl(url)) {
        return {
          datasetId: id,
          kind: "direct",
          provider: String(distribution.provider ?? "") || undefined,
          method: String(distribution.download_method ?? "navigate"),
          url,
          filename: String(distribution.filename ?? "") || undefined,
          requiresAuth: false,
          metadata: distribution
        };
      }
    }

    const methods = Array.isArray(dataset.programmatic_access)
      ? dataset.programmatic_access.filter((item: unknown) => item && typeof item === "object")
      : [];
    if (methods.length) {
      const method = methods[0] as RecordLike;
      return {
        datasetId: id,
        kind: "programmatic",
        provider: String(method.provider ?? "") || undefined,
        method: String(method.method ?? "") || undefined,
        url: isHttpUrl(method.documentation_url) ? method.documentation_url : undefined,
        requiresAuth: method.requires_auth === true,
        metadata: method.method === "http_files"
          ? { ...method, files: distributions }
          : method
      };
    }

    return {
      datasetId: id,
      kind: "site",
      url: isHttpUrl(dataset.access) ? dataset.access : undefined,
      requiresAuth: false,
      metadata: { access: dataset.access ?? null }
    };
  }

  /* Convenience helpers */
  datasets() { return this.list("datasets"); }
  models() { return this.list("models"); }
  useCases() { return this.list("useCases"); }
  tools() { return this.list("tools"); }
  guides() { return this.list("guides"); }
  oer() { return this.list("oer"); }
  contributors() { return this.list("contributors"); }

  objectVocab() { return this.catalog("objectVocab"); }
  objectTaxonomyConfig() { return this.catalog("objectTaxonomyConfig"); }
}
