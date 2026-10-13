ALTER TABLE public.profiles
    ADD COLUMN IF NOT EXISTS download_allowed boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS download_requested boolean NOT NULL DEFAULT false;

CREATE TABLE IF NOT EXISTS public.support_messages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    sender_email text NOT NULL REFERENCES public.profiles(email),
    subject text NOT NULL CHECK (length(subject) BETWEEN 1 AND 200),
    message text NOT NULL CHECK (length(message) BETWEEN 1 AND 10000),
    created_at timestamptz NOT NULL DEFAULT now(),
    read_at timestamptz
);

CREATE INDEX IF NOT EXISTS support_messages_created_at_idx
    ON public.support_messages (created_at DESC);

CREATE OR REPLACE FUNCTION public.can_manage_system()
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM public.profiles
        WHERE lower(email) = lower(auth.jwt() ->> 'email')
          AND role IN ('Administrador', 'Super Administrador')
          AND status = 'Activo'
    );
$$;

REVOKE ALL ON FUNCTION public.can_manage_system() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.can_manage_system() TO authenticated;

CREATE OR REPLACE FUNCTION public.admin_update_profile(
    target_email text,
    new_role text,
    new_status text,
    new_download_allowed boolean
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF NOT public.can_manage_system() THEN
        RAISE EXCEPTION 'Administrator access is required';
    END IF;
    IF new_role NOT IN (
        'Sin Rol Asignado',
        'Visualizador',
        'Modificador',
        'Administrador',
        'Super Administrador'
    ) OR new_status NOT IN ('Pendiente', 'Activo', 'Inactivo') THEN
        RAISE EXCEPTION 'Invalid role or status';
    END IF;
    IF lower(target_email) = lower(auth.jwt() ->> 'email')
       AND (new_role <> 'Super Administrador' OR new_status <> 'Activo') THEN
        RAISE EXCEPTION 'The active administrator cannot remove their own access';
    END IF;

    UPDATE public.profiles
    SET role = new_role,
        status = new_status,
        download_allowed = new_download_allowed
            OR new_role IN ('Modificador', 'Administrador', 'Super Administrador'),
        download_requested = false
    WHERE lower(email) = lower(target_email);
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Profile not found';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION public.request_document_download()
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    UPDATE public.profiles
    SET download_requested = true
    WHERE lower(email) = lower(auth.jwt() ->> 'email')
      AND status = 'Activo'
      AND role = 'Visualizador'
      AND NOT download_allowed;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'The profile is not eligible to request document downloads';
    END IF;
END;
$$;

REVOKE ALL ON FUNCTION public.admin_update_profile(text, text, text, boolean)
    FROM PUBLIC;
REVOKE ALL ON FUNCTION public.request_document_download() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.admin_update_profile(text, text, text, boolean)
    TO authenticated;
GRANT EXECUTE ON FUNCTION public.request_document_download() TO authenticated;

ALTER TABLE public.support_messages ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS support_messages_select_own_or_admin
    ON public.support_messages;
CREATE POLICY support_messages_select_own_or_admin
    ON public.support_messages FOR SELECT TO authenticated
    USING (
        lower(sender_email) = lower(auth.jwt() ->> 'email')
        OR public.can_manage_system()
    );

DROP POLICY IF EXISTS support_messages_insert_own
    ON public.support_messages;
CREATE POLICY support_messages_insert_own
    ON public.support_messages FOR INSERT TO authenticated
    WITH CHECK (
        lower(sender_email) = lower(auth.jwt() ->> 'email')
    );

DROP POLICY IF EXISTS support_messages_update_admin
    ON public.support_messages;
CREATE POLICY support_messages_update_admin
    ON public.support_messages FOR UPDATE TO authenticated
    USING (public.can_manage_system())
    WITH CHECK (public.can_manage_system());

GRANT SELECT, INSERT ON public.support_messages TO authenticated;
GRANT UPDATE (read_at) ON public.support_messages TO authenticated;
