-- Tools Forge — Plans Seed v2
-- 3 monthly + 2 yearly

INSERT INTO public.plans 
  (name, display_name, price_usd, max_requests, billing_period, rate_limit_per_min, allowed_tools)
VALUES 
  ('free',  'مجاني', 0.00,   500,    'monthly', 5,   '["smart-data-converter"]'::jsonb),
  ('basic', 'أساسي', 9.00,   5000,   'monthly', 30,  '["all"]'::jsonb),
  ('basic', 'أساسي', 86.00,  5000,   'yearly',  30,  '["all"]'::jsonb),
  ('pro',   'متقدم', 29.00,  50000,  'monthly', 100, '["all"]'::jsonb),
  ('pro',   'متقدم', 278.00, 50000,  'yearly',  100, '["all"]'::jsonb);
