// Copyright (c) 2024-2026 OpenConstruction Open Science Initiative
// SPDX-License-Identifier: Apache-2.0
import { CATALOGS } from "./registry.js";
const DEFAULT_BASE = "https://www.openconstruction.org";
function joinUrl(base, path) {
    return `${base.replace(/\/+$/, "")}/${path.replace(/^\/+/, "")}`;
}
function normalizeToArray(raw) {
    if (Array.isArray(raw))
        return raw;
    // envelope: { datasets: [...] } or { models: [...] } etc.
    if (raw && typeof raw === "object") {
        for (const v of Object.values(raw)) {
            if (Array.isArray(v))
                return v;
        }
        // map: { ID: {...}, ... }
        return Object.values(raw);
    }
    return [];
}
function getByIdFromRaw(raw, id) {
    if (raw && typeof raw === "object" && !Array.isArray(raw)) {
        const direct = raw[id];
        if (direct && typeof direct === "object")
            return direct;
    }
    const arr = normalizeToArray(raw);
    return arr.find(r => r?.id === id) ?? null;
}
function includesQuery(haystack, needle, caseSensitive) {
    return caseSensitive
        ? haystack.includes(needle)
        : haystack.toLowerCase().includes(needle.toLowerCase());
}
function isHttpUrl(value) {
    if (typeof value !== "string" || !value.trim())
        return false;
    try {
        const url = new URL(value);
        return url.protocol === "http:" || url.protocol === "https:";
    }
    catch {
        return false;
    }
}
export class OpenConstructionClient {
    baseUrl;
    fetchImpl;
    noCache;
    constructor(opts = {}) {
        this.baseUrl = opts.baseUrl ?? DEFAULT_BASE;
        this.fetchImpl = opts.fetchImpl ?? fetch;
        this.noCache = !!opts.noCache;
    }
    setBaseUrl(baseUrl) {
        this.baseUrl = baseUrl;
    }
    async fetchJSON(path) {
        const url = joinUrl(this.baseUrl, path);
        const res = await this.fetchImpl(url, { cache: this.noCache ? "no-store" : "default" });
        if (!res.ok)
            throw new Error(`OpenConstruction fetch failed (${res.status}): ${url}`);
        return (await res.json());
    }
    /** Load raw catalog JSON */
    async catalog(key) {
        return this.fetchJSON(CATALOGS[key]);
    }
    /** Normalize catalog to array (supports array, envelope, or map form) */
    async list(key) {
        const raw = await this.catalog(key);
        return normalizeToArray(raw);
    }
    /** Get record by ID (supports map + array forms) */
    async get(key, id) {
        const raw = await this.catalog(key);
        return getByIdFromRaw(raw, id);
    }
    /** Keyword search */
    async search(key, query, opts = {}) {
        const q = (query ?? "").trim();
        if (!q)
            return [];
        const limit = opts.limit ?? 200;
        const caseSensitive = !!opts.caseSensitive;
        const fields = opts.fields;
        const rows = await this.list(key);
        const out = [];
        for (const r of rows) {
            let blob;
            if (fields?.length) {
                blob = fields
                    .map(f => r?.[f])
                    .filter(v => v != null)
                    .map(String)
                    .join(" ");
            }
            else {
                blob = JSON.stringify(r);
            }
            if (includesQuery(blob, q, caseSensitive)) {
                out.push(r);
                if (out.length >= limit)
                    break;
            }
        }
        return out;
    }
    /** Resolve the machine-readable retrieval strategy used by UI and MCP clients. */
    async datasetDownloadPlan(id) {
        const dataset = await this.get("datasets", id);
        if (!dataset)
            return null;
        const distributions = Array.isArray(dataset.distribution)
            ? dataset.distribution.filter((item) => item && typeof item === "object")
            : [];
        if (distributions.length === 1) {
            const distribution = distributions[0];
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
            ? dataset.programmatic_access.filter((item) => item && typeof item === "object")
            : [];
        if (methods.length) {
            const method = methods[0];
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
