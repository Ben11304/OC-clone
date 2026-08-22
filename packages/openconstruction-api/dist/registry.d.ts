export declare const CATALOGS: {
    readonly datasets: "data/datasets.json";
    readonly models: "data/models.json";
    readonly useCases: "data/use-cases.json";
    readonly tools: "data/tools.json";
    readonly guides: "data/guides.json";
    readonly oer: "data/oer.json";
    readonly contributors: "data/contributors.json";
    readonly objectVocab: "data/object_vocab.json";
    readonly objectTaxonomyConfig: "data/object_taxonomy_config.json";
};
export type CatalogKey = keyof typeof CATALOGS;
