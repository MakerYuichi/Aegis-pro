-- Purge Razorpay-branded seed data from existing databases.
--
-- Context: 001_create_services.sql and 003_create_oncall_tables.sql
-- previously seeded rows with @razorpay.com emails and @rahul/@priya/etc
-- handles. Those files are now fixed, but existing databases still hold
-- the old rows. This migration cleans them up on next startup.
--
-- Safe to run repeatedly: each DELETE is a no-op if the rows are gone.

-- Remove Razorpay-branded on-call rotations
DELETE FROM oncall_rotations WHERE email LIKE '%@razorpay.com';

-- Remove Razorpay-branded escalation policies
DELETE FROM escalation_policies WHERE email LIKE '%@razorpay.com';

-- Remove services whose on_call handles are the old Razorpay set
-- (the row itself is still valid; only the handle array is stale)
UPDATE services
SET on_call = '[]'::jsonb
WHERE on_call::text LIKE '%@rahul%'
   OR on_call::text LIKE '%@priya%'
   OR on_call::text LIKE '%@amit%'
   OR on_call::text LIKE '%@sneha%'
   OR on_call::text LIKE '%@vikram%'
   OR on_call::text LIKE '%@ananya%'
   OR on_call::text LIKE '%@arjun%'
   OR on_call::text LIKE '%@shreya%'
   OR on_call::text LIKE '%@manish%';
