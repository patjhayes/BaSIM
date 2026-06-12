-- 001_initial_schema.sql
-- Contains schema for simulation queue and token credit system

-- 1. Create Enums
CREATE TYPE job_status AS ENUM ('queued', 'running', 'completed', 'failed');

-- 2. Create Tables
CREATE TABLE company_wallets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_name TEXT NOT NULL,
    credit_balance INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE credit_ledger (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES company_wallets(id),
    user_id UUID NOT NULL,
    project_code TEXT NOT NULL,
    credits_used INTEGER NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE simulation_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES company_wallets(id),
    user_id UUID NOT NULL,
    project_code TEXT NOT NULL,
    status job_status NOT NULL DEFAULT 'queued',
    payload JSONB NOT NULL,
    result JSONB,
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 3. Stored Procedure for Safe Row-Locking (SELECT ... FOR UPDATE SKIP LOCKED)
-- This function allows workers to safely pop jobs off the queue concurrently
CREATE OR REPLACE FUNCTION get_next_queued_job(worker_id TEXT)
RETURNS TABLE (
    job_id UUID,
    job_payload JSONB,
    job_company_id UUID,
    job_project_code TEXT
) 
LANGUAGE plpgsql
AS $$
DECLARE
    selected_job_id UUID;
BEGIN
    -- Find the oldest queued job and lock it
    SELECT id INTO selected_job_id
    FROM simulation_jobs
    WHERE status = 'queued'
    ORDER BY created_at ASC
    FOR UPDATE SKIP LOCKED
    LIMIT 1;

    IF selected_job_id IS NOT NULL THEN
        -- Update its status to running
        UPDATE simulation_jobs
        SET status = 'running', updated_at = NOW()
        WHERE id = selected_job_id;

        -- Return the job details
        RETURN QUERY 
        SELECT id, payload, company_id, project_code 
        FROM simulation_jobs 
        WHERE id = selected_job_id;
    END IF;
END;
$$;
