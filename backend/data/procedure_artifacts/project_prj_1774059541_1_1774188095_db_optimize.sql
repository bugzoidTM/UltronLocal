-- Generated optimization suggestions (safe review first)
PRAGMA optimize;
ANALYZE;
-- Consider index review for frequent filters/order patterns
-- CREATE INDEX IF NOT EXISTS idx_triples_sp ON triples(subject, predicate);
