ALTER TABLE intercom ADD COLUMN IF NOT EXISTS priority INTEGER NOT NULL DEFAULT 0;
UPDATE version SET version='v3.5';
