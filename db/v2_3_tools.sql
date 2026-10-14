-- Tools Forge v2.3 — Tool Registry
-- Central registry for all tools (smart-data-converter + future)
BEGIN;

CREATE TABLE IF NOT EXISTS public.tools (
    id              TEXT PRIMARY KEY,       -- stable id (never change)
    display_name    TEXT NOT NULL,          -- marketing name (changeable)
    description     TEXT,
    version         TEXT NOT NULL DEFAULT '1.0.0',
    api_base_path   TEXT NOT NULL,          -- e.g. '/v1/convert'
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    input_schema    JSONB,
    output_schema   JSONB,
    metadata        JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.tools ENABLE ROW LEVEL SECURITY;

-- Public read for active tools (for the /v1/tools endpoint)
DROP POLICY IF EXISTS "Public read active tools" ON public.tools;
CREATE POLICY "Public read active tools"
    ON public.tools FOR SELECT
    USING (is_active = TRUE);

GRANT SELECT ON public.tools TO anon;
GRANT SELECT ON public.tools TO authenticated;
GRANT ALL ON public.tools TO service_role;

-- Seed the first tool (idempotent)
INSERT INTO public.tools (id, display_name, description, version, api_base_path, input_schema, output_schema, metadata)
VALUES (
    'smart-data-converter',
    'Smart Data Converter',
    'تحويل ملفات CSV و HTML إلى JSON نظيف ومنظم',
    '1.1.3',
    '/v1/convert',
    '{"csv": "multipart/form-data (file)", "html": "application/json (html)"}'::jsonb,
    '{"success": "boolean", "data": "array", "columns": "array"}'::jsonb,
    '{"status": "available", "docs": "/docs"}'::jsonb
)
ON CONFLICT (id) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    description = EXCLUDED.description,
    updated_at = NOW();

COMMIT;
