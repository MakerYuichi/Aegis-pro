INSERT INTO services (name, description, repo_name, on_call, dependencies, is_critical) VALUES
('payment-api', 'Handles all payment processing - UPI, Cards, Netbanking', 'payment-service', '["@rahul", "@priya"]', '["auth", "ledger", "fraud"]', TRUE),
('auth', 'Authentication and authorization service', 'auth-service', '["@amit", "@sneha"]', '["user"]', TRUE),
('ledger', 'Transaction ledger and accounting', 'ledger-service', '["@vikram", "@shreya"]', '["database"]', TRUE),
('refund', 'Refund and reversal processing', 'refund-service', '["@ananya"]', '["payment-api", "auth"]', FALSE),
('fraud', 'Fraud detection and risk scoring', 'fraud-service', '["@raj"]', '["payment-api", "auth"]', FALSE),
('notification', 'Email, SMS and push notifications', 'notification-service', '["@kavya"]', '["user"]', FALSE),
('user', 'User profile and KYC management', 'user-service', '["@arjun"]', '[]', FALSE),
('database', 'Database operations and migrations', 'database-service', '["@shreya", "@manish"]', '[]', TRUE);

COMMENT ON TABLE services IS 'Service catalog with ownership and dependency mapping';