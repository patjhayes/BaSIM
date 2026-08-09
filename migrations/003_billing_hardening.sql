-- Atomic, idempotent Stripe purchases and restricted credit operations.

ALTER TABLE public.transactions
    ADD COLUMN IF NOT EXISTS external_reference TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS transactions_purchase_reference_key
    ON public.transactions (external_reference)
    WHERE type = 'purchase'
      AND external_reference IS NOT NULL;

CREATE OR REPLACE FUNCTION public.credit_project_purchase(
    p_project_code TEXT,
    p_user_id UUID,
    p_checkout_session_id TEXT,
    p_amount INTEGER DEFAULT 1000,
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
    IF p_amount <= 0 THEN
        RAISE EXCEPTION 'INVALID_CREDIT_AMOUNT';
    END IF;

    SELECT credit_balance
      INTO current_balance
      FROM public.projects
     WHERE project_code = p_project_code
     FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'PROJECT_NOT_FOUND';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM public.transactions
         WHERE external_reference = p_checkout_session_id
           AND type = 'purchase'
    ) THEN
        RETURN current_balance;
    END IF;

    UPDATE public.projects
       SET credit_balance = credit_balance + p_amount
     WHERE project_code = p_project_code
     RETURNING credit_balance INTO current_balance;

    INSERT INTO public.transactions (
        project_code,
        amount,
        type,
        user_id,
        description,
        external_reference
    ) VALUES (
        p_project_code,
        p_amount,
        'purchase',
        p_user_id,
        p_description,
        p_checkout_session_id
    );

    RETURN current_balance;
END;
$$;

CREATE OR REPLACE FUNCTION public.adjust_project_credits(
    p_project_code TEXT,
    p_user_id UUID,
    p_amount INTEGER,
    p_description TEXT
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    current_balance INTEGER;
BEGIN
    UPDATE public.projects
       SET credit_balance = credit_balance + p_amount
     WHERE project_code = p_project_code
       AND credit_balance + p_amount >= 0
     RETURNING credit_balance INTO current_balance;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'PROJECT_NOT_FOUND_OR_NEGATIVE_BALANCE';
    END IF;

    INSERT INTO public.transactions (
        project_code,
        amount,
        type,
        user_id,
        description
    ) VALUES (
        p_project_code,
        p_amount,
        'manual_adjustment',
        p_user_id,
        p_description
    );

    RETURN current_balance;
END;
$$;

REVOKE ALL ON FUNCTION public.debit_analysis_credit(TEXT, TEXT, UUID, UUID, TEXT)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.refund_analysis_credit(TEXT, UUID, UUID, TEXT)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.credit_project_purchase(TEXT, UUID, TEXT, INTEGER, TEXT)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.adjust_project_credits(TEXT, UUID, INTEGER, TEXT)
    FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.debit_analysis_credit(TEXT, TEXT, UUID, UUID, TEXT)
    TO service_role;
GRANT EXECUTE ON FUNCTION public.refund_analysis_credit(TEXT, UUID, UUID, TEXT)
    TO service_role;
GRANT EXECUTE ON FUNCTION public.credit_project_purchase(TEXT, UUID, TEXT, INTEGER, TEXT)
    TO service_role;
GRANT EXECUTE ON FUNCTION public.adjust_project_credits(TEXT, UUID, INTEGER, TEXT)
    TO service_role;