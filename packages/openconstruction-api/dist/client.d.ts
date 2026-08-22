import { type CatalogKey } from "./registry.js";
import type { ClientOptions, DatasetDownloadPlan, RecordLike, SearchOptions } from "./types.js";
export declare class OpenConstructionClient {
    private baseUrl;
    private fetchImpl;
    private noCache;
    constructor(opts?: ClientOptions);
    setBaseUrl(baseUrl: string): void;
    fetchJSON<T = any>(path: string): Promise<T>;
    /** Load raw catalog JSON */
    catalog<T = any>(key: CatalogKey): Promise<T>;
    /** Normalize catalog to array (supports array, envelope, or map form) */
    list(key: CatalogKey): Promise<RecordLike[]>;
    /** Get record by ID (supports map + array forms) */
    get(key: CatalogKey, id: string): Promise<RecordLike | null>;
    /** Keyword search */
    search(key: CatalogKey, query: string, opts?: SearchOptions): Promise<RecordLike[]>;
    /** Resolve the machine-readable retrieval strategy used by UI and MCP clients. */
    datasetDownloadPlan(id: string): Promise<DatasetDownloadPlan | null>;
    datasets(): Promise<RecordLike[]>;
    models(): Promise<RecordLike[]>;
    useCases(): Promise<RecordLike[]>;
    tools(): Promise<RecordLike[]>;
    guides(): Promise<RecordLike[]>;
    oer(): Promise<RecordLike[]>;
    contributors(): Promise<RecordLike[]>;
    objectVocab(): Promise<any>;
    objectTaxonomyConfig(): Promise<any>;
}
