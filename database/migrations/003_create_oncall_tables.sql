-- On-call rotations table
CREATE TABLE IF NOT EXISTS oncall_rotations (
    id SERIAL PRIMARY KEY,
    service_name VARCHAR(255) NOT NULL,
    engineer_name VARCHAR(255) NOT NULL,
    slack_handle VARCHAR(100) NOT NULL,
    email VARCHAR(255),
    phone VARCHAR(20),
    role VARCHAR(50) DEFAULT 'primary',
    is_active BOOLEAN DEFAULT TRUE,
    start_date TIMESTAMP,
    end_date TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Escalation policies table
CREATE TABLE IF NOT EXISTS escalation_policies (
    id SERIAL PRIMARY KEY,
    service_name VARCHAR(255) NOT NULL,
    severity VARCHAR(10) NOT NULL,
    escalation_level INTEGER DEFAULT 1,
    engineer_name VARCHAR(255),
    slack_handle VARCHAR(100),
    email VARCHAR(255),
    phone VARCHAR(20),
    wait_time_minutes INTEGER DEFAULT 5,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Seed on-call data (fictional dataset — see README "Demo Mode")
INSERT INTO oncall_rotations (service_name, engineer_name, slack_handle, email, phone, role) VALUES
('payment-api', 'Marcus Chen',     '@marcus',  'marcus.chen@acme-demo.com',     '+1-415-555-0101', 'primary'),
('payment-api', 'prisha Raman',     '@prisha',   'prisha.raman@acme-demo.com',     '+1-415-555-0102', 'secondary'),
('payment-api', 'Tomas Alvarez',   '@tomas',   'tomas.alvarez@acme-demo.com',   '+1-415-555-0103', 'tertiary'),
('auth',        'Dana Okafor',     '@dana',    'dana.okafor@acme-demo.com',     '+1-415-555-0201', 'primary'),
('auth',        'Wei Zhang',       '@wei',     'wei.zhang@acme-demo.com',       '+1-415-555-0202', 'secondary'),
('ledger',      'Sofia Marchetti', '@sofia',   'sofia.marchetti@acme-demo.com', '+1-415-555-0301', 'primary'),
('ledger',      'Ade Balogun',     '@ade',     'ade.balogun@acme-demo.com',     '+1-415-555-0302', 'secondary'),
('database',    'Rina Takahashi',  '@rina',    'rina.takahashi@acme-demo.com',  '+1-415-555-0401', 'primary'),
('database',    'Youssef Hamdi',   '@youssef', 'youssef.hamdi@acme-demo.com',   '+1-415-555-0402', 'secondary');

-- Seed escalation policies
INSERT INTO escalation_policies (service_name, severity, escalation_level, engineer_name, slack_handle, email, phone, wait_time_minutes) VALUES
('payment-api', 'P0', 1, 'Marcus Chen',   '@marcus', 'marcus.chen@acme-demo.com',    '+1-415-555-0101', 5),
('payment-api', 'P0', 2, 'prisha Raman',   '@prisha',  'prisha.raman@acme-demo.com',    '+1-415-555-0102', 5),
('payment-api', 'P0', 3, 'Tomas Alvarez', '@tomas',  'tomas.alvarez@acme-demo.com',  '+1-415-555-0103', 5),
('payment-api', 'P1', 1, 'prisha Raman',   '@prisha',  'prisha.raman@acme-demo.com',    '+1-415-555-0102', 15),
('auth',        'P0', 1, 'Dana Okafor',   '@dana',   'dana.okafor@acme-demo.com',    '+1-415-555-0201', 5),
('auth',        'P0', 2, 'Wei Zhang',     '@wei',    'wei.zhang@acme-demo.com',      '+1-415-555-0202', 10);
