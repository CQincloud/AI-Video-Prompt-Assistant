BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'membership_levels_points_no_overlap'
          AND conrelid = 'membership_levels'::regclass
    ) THEN
        ALTER TABLE membership_levels
        ADD CONSTRAINT membership_levels_points_no_overlap
        EXCLUDE USING gist (
            int4range(min_points, max_points, '[)') WITH &&
        );
    END IF;
END;
$$;

COMMIT;
