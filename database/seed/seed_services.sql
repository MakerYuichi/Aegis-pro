-- Seed service catalog (fictional dataset — see README "Demo Mode")
INSERT INTO services (name, description, repo_name, on_call, dependencies, is_critical) VALUES
('payment-api', 'Payment processing — cards, wallets, bank transfers', 'payment-service', '["@marcus", "@priya"]', '["auth", "ledger", "fraud"]', TRUE),
('auth',        'Authentication and authorization',                    'auth-service',    '["@dana", "@wei"]',     '["user"]',                   TRUE),
('ledger',      'Transaction ledger and accounting',                   'ledger-service',  '["@sofia", "@ade"]',    '["database"]',               TRUE),
('refund',      'Refund and reversal processing',                      'refund-service',  '["@nina"]',             '["payment-api", "auth"]',    FALSE),
('fraud',       'Fraud detection and risk scoring',                    'fraud-service',   '["@omar"]',             '["payment-api", "auth"]',    FALSE),
('notification','Email, SMS, and push notifications',                  'notification-service', '["@lila"]',       '["user"]',                   FALSE),
('user',        'User profile and KYC management',                     'user-service',    '["@kenji"]',            '[]',                         FALSE),
('database',    'Database operations and migrations',                  'database-service','["@rina", "@youssef"]', '[]',                         TRUE);

COMMENT ON TABLE services IS 'Service catalog with ownership and dependency mapping';