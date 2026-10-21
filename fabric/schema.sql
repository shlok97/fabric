PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS principals (
 id TEXT PRIMARY KEY, workspace TEXT NOT NULL, tenant TEXT NOT NULL,
 name TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE, active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS collections (
 id TEXT PRIMARY KEY, workspace TEXT NOT NULL, tenant TEXT,
 name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS grants (
 collection_id TEXT NOT NULL REFERENCES collections(id), tenant TEXT NOT NULL,
 principal TEXT NOT NULL DEFAULT '',
 PRIMARY KEY (collection_id, tenant, principal)
);
CREATE TABLE IF NOT EXISTS connections (
 id TEXT PRIMARY KEY, collection_id TEXT NOT NULL REFERENCES collections(id),
 kind TEXT NOT NULL CHECK(kind IN ('folder', 'sqlite')),
 config TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
 last_success TEXT, last_error TEXT
);
CREATE TABLE IF NOT EXISTS documents (
 id TEXT PRIMARY KEY, connection_id TEXT NOT NULL REFERENCES connections(id),
 external_id TEXT NOT NULL, title TEXT NOT NULL, version TEXT NOT NULL,
 principal TEXT NOT NULL DEFAULT '', observed_at TEXT NOT NULL,
 active INTEGER NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX IF NOT EXISTS current_documents ON documents(connection_id, external_id) WHERE active = 1;
CREATE TABLE IF NOT EXISTS passages (
 id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
 ordinal INTEGER NOT NULL, text TEXT NOT NULL, start_line INTEGER NOT NULL, end_line INTEGER NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS passage_fts USING fts5(passage_id UNINDEXED, text, tokenize='unicode61');
CREATE TABLE IF NOT EXISTS descriptors (
 id TEXT PRIMARY KEY, connection_id TEXT NOT NULL REFERENCES connections(id),
 title TEXT NOT NULL, description TEXT NOT NULL, metric TEXT NOT NULL, unit TEXT NOT NULL,
 version INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS numeric_refs (
 id TEXT PRIMARY KEY, principal TEXT NOT NULL REFERENCES principals(id),
 descriptor_id TEXT NOT NULL REFERENCES descriptors(id), selectors TEXT NOT NULL,
 version TEXT NOT NULL, row_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS receipts (
 id TEXT PRIMARY KEY, principal TEXT NOT NULL, operation TEXT NOT NULL, status TEXT NOT NULL,
 elapsed_ms REAL NOT NULL, bytes INTEGER NOT NULL, items INTEGER NOT NULL,
 source_calls INTEGER NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS vectors (
 passage_id TEXT NOT NULL REFERENCES passages(id), model TEXT NOT NULL,
 embedding BLOB NOT NULL, PRIMARY KEY(passage_id,model)
);
