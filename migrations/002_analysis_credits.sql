-- Atomic, idempotent credit accounting for Redis/Celery analysis jobs.

ALTER TABLE public.transactions
    ADD COLUMN IF NOT EXISTS analysis_job_id UUID;

CREATE UNIQUE INDEX IF NOT EXISTS transactions_analysis_job_type_key
    ON public.transactions (analysis_job_id, type)
    WHERE analysis_job_id IS NOT NULL
      AND type IN ('analysis_debit', 'analysis_refund');

CREATE OR REPLACE FUNCTION public.debit_analysis_credit(
    p_project_code TEXT,
    p_company_id TEXT,
    p_user_id UUID,
    p_job_id UUID,
    p_description TEXT DEFAULT NULL
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    project_company_id TEXT;
    current_balance INTEGER;
BEGIN
    SELECT company_id, credit_balance
      INTO project_company_id, current_balance
      FROM public.projects
     WHERE project_code = p_project_code
     FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'PROJECT_NOT_FOUND';
    END IF;
    IF project_company_id IS DISTINCT FROM p_company_id THEN
        RAISE EXCEPTION 'PROJECT_FORBIDDEN';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM public.transactions
         WHERE analysis_job_id = p_job_id
           AND type = 'analysis_debit'
    ) THEN
        RETURN current_balance;
    END IF;
    IF current_balance < 1 THEN
        RAISE EXCEPTION 'INSUFFICIENT_CREDITS';
    END IF;

    UPDATE public.projects
       SET credit_balance = credit_balance - 1
     WHERE project_code = p_project_code
     RETURNING credit_balance INTO current_balance;

    INSERT INTO public.transactions (
        project_code,
        amount,
        type,
        user_id,
        description,
        analysis_job_id
    ) VALUES (
        p_project_code,
        -1,
        'analysis_debit',
        p_user_id,
        p_description,
        p_job_id
    );

    RETURN current_balance;
END;
$$;

CREATE OR REPLACE FUNCTION public.refund_analysis_credit(
    p_project_code TEXT,
    p_user_id UUID,
    p_job_id UUID,
    p_description TEXT DEFAULT NULL
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    current_balance INTEGER;
BEGIN
    SELECT credit_balance
      INTO current_balance
      FROM public.projects
     WHERE project_code = p_project_code
     FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'PROJECT_NOT_FOUND';
    END IF;
    IF NOT EXISTS (
        SELECT 1
          FROM public.transactions
         WHERE analysis_job_id = p_job_id
           AND type = 'analysis_debit'
    ) THEN
        RAISE EXCEPTION 'ANALYSIS_DEBIT_NOT_FOUND';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM public.transactions
         WHERE analysis_job_id = p_job_id
           AND type = 'analysis_refund'
    ) THEN
        RETURN current_balance;
    END IF;

    UPDATE public.projects
       SET credit_balance = credit_balance + 1
     WHERE project_code = p_project_code
     RETURNING credit_balance INTO current_balance;

    INSERT INTO public.transactions (
        project_code,
        amount,
        type,
        user_id,
        description,
        analysis_job_id
    ) VALUES (
        p_project_code,
        1,
        'analysis_refund',
        p_user_id,
        p_description,
        p_job_id
    );

    RETURN current_balance;
END;
$$;