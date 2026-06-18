-- BaSIM Billing and Auth Schema for Supabase

-- 1. Create Companies table
CREATE TABLE IF NOT EXISTS public.companies (
    id TEXT PRIMARY KEY, -- e.g., 'innealta.com.au' or a solo identifier
    name TEXT NOT NULL,
    is_solo BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 2. Create Profiles table (links auth.users to companies)
CREATE TABLE IF NOT EXISTS public.profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    company_id TEXT REFERENCES public.companies(id) ON DELETE CASCADE,
    is_admin BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 3. Create Projects table (holds the credit balance)
CREATE TABLE IF NOT EXISTS public.projects (
    project_code TEXT PRIMARY KEY,
    company_id TEXT REFERENCES public.companies(id) ON DELETE CASCADE,
    credit_balance INTEGER DEFAULT 0 NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 4. Create Transactions ledger table
CREATE TABLE IF NOT EXISTS public.transactions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_code TEXT REFERENCES public.projects(project_code) ON DELETE CASCADE,
    amount INTEGER NOT NULL,
    type TEXT NOT NULL, -- 'purchase', 'simulation', 'manual_adjustment'
    user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Enable Row Level Security (RLS)
ALTER TABLE public.companies ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.transactions ENABLE ROW LEVEL SECURITY;

-- Simple Policies (Adjust as needed for strict security)
-- Allow authenticated users to view their own company
CREATE POLICY "Users can view their own company" ON public.companies
    FOR SELECT USING (
        id IN (SELECT company_id FROM public.profiles WHERE id = auth.uid())
    );

-- Allow users to view their own profile
CREATE POLICY "Users can view own profile" ON public.profiles
    FOR SELECT USING (id = auth.uid());

-- Allow users to view projects within their company
CREATE POLICY "Users can view company projects" ON public.projects
    FOR SELECT USING (
        company_id IN (SELECT company_id FROM public.profiles WHERE id = auth.uid())
    );

-- Allow users to insert new projects into their company
CREATE POLICY "Users can insert company projects" ON public.projects
    FOR INSERT WITH CHECK (
        company_id IN (SELECT company_id FROM public.profiles WHERE id = auth.uid())
    );

-- Allow users to view their project transactions
CREATE POLICY "Users can view company transactions" ON public.transactions
    FOR SELECT USING (
        project_code IN (SELECT project_code FROM public.projects WHERE company_id IN (SELECT company_id FROM public.profiles WHERE id = auth.uid()))
    );

-- NOTE: Modifying credit balances and creating transactions will be handled by the backend using a Service Role Key, 
-- which bypasses RLS. Therefore, we do not need to grant INSERT/UPDATE policies to clients for billing tables.

-- 5. Trigger to automatically create a profile and company when a user signs up
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
    generic_domains TEXT[] := ARRAY['gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com', 'live.com', 'icloud.com', 'me.com', 'msn.com'];
BEGIN
    -- Extract domain
    domain := split_part(NEW.email, '@', 2);
    
    -- Check if generic
    is_generic := domain = ANY(generic_domains);
    
    IF is_generic THEN
        comp_id := 'solo_' || NEW.id::TEXT;
        comp_name := 'Personal Workspace';
    ELSE
        comp_id := domain;
        comp_name := domain;
    END IF;

    -- Upsert company
    INSERT INTO public.companies (id, name, is_solo)
    VALUES (comp_id, comp_name, is_generic)
    ON CONFLICT (id) DO NOTHING;

    -- Insert profile
    INSERT INTO public.profiles (id, email, company_id, is_admin)
    VALUES (
        NEW.id, 
        NEW.email, 
        comp_id, 
        CASE WHEN NEW.email = 'Patrick@innealta.com.au' THEN true ELSE false END
    );

    RETURN NEW;
END;
$$;

-- Bind the trigger
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE PROCEDURE public.handle_new_user();
