-- 004_rls_policies.sql
-- Row Level Security policies for the articles table.

-- Enable RLS on articles
ALTER TABLE articles ENABLE ROW LEVEL SECURITY;

-- Anyone can read articles (public access for the MVP)
CREATE POLICY "Articles are publicly readable"
    ON articles
    FOR SELECT
    USING (true);

-- Only the service role can insert new articles
CREATE POLICY "Service role can insert articles"
    ON articles
    FOR INSERT
    WITH CHECK (
        (current_setting('request.jwt.claims', true)::jsonb ->> 'role') = 'service_role'
    );

-- Only the service role can update articles
CREATE POLICY "Service role can update articles"
    ON articles
    FOR UPDATE
    USING (
        (current_setting('request.jwt.claims', true)::jsonb ->> 'role') = 'service_role'
    );

-- Only the service role can delete articles
CREATE POLICY "Service role can delete articles"
    ON articles
    FOR DELETE
    USING (
        (current_setting('request.jwt.claims', true)::jsonb ->> 'role') = 'service_role'
    );
