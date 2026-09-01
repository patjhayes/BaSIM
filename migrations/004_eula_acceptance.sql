-- Record explicit web EULA acceptance for new and existing BaSIM users.

ALTER TABLE public.profiles
    ADD COLUMN IF NOT EXISTS eula_version TEXT;

ALTER TABLE public.profiles
    ADD COLUMN IF NOT EXISTS eula_accepted_at TIMESTAMP WITH TIME ZONE;

CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    domain TEXT;
    is_generic BOOLEAN;
    comp_id TEXT;
    comp_name TEXT;
    generic_domains TEXT[] := ARRAY[
        'gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com', 'live.com',
        'icloud.com', 'me.com', 'msn.com'
    ];
BEGIN
    domain := split_part(NEW.email, '@', 2);
    is_generic := domain = ANY(generic_domains);

    IF is_generic THEN
        comp_id := 'solo_' || NEW.id::TEXT;
        comp_name := 'Personal Workspace';
    ELSE
        comp_id := domain;
        comp_name := domain;
    END IF;

    INSERT INTO public.companies (id, name, is_solo)
    VALUES (comp_id, comp_name, is_generic)
    ON CONFLICT (id) DO NOTHING;

    INSERT INTO public.profiles (
        id, email, company_id, is_admin, eula_version, eula_accepted_at
    )
    VALUES (
        NEW.id,
        NEW.email,
        comp_id,
        CASE WHEN NEW.email = 'Patrick@innealta.com.au' THEN true ELSE false END,
           CASE WHEN NEW.raw_user_meta_data ->> 'eula_accepted' = 'true'
                    AND NEW.raw_user_meta_data ->> 'eula_version' = '2026-09-02-placeholder'
               THEN NEW.raw_user_meta_data ->> 'eula_version' ELSE NULL END,
           CASE WHEN NEW.raw_user_meta_data ->> 'eula_accepted' = 'true'
                    AND NEW.raw_user_meta_data ->> 'eula_version' = '2026-09-02-placeholder'
             THEN timezone('utc'::text, now()) ELSE NULL END
    );

    RETURN NEW;
END;
$$;
