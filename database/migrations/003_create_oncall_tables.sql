CREATE TABLE IF NOT EXISTS oncall_rotations (
    id SERIAL PRIMARY KEY,
    service_name VARCHAR(255) NOT NULL,
    engineer_name VARCHAR(255) NOT NULL,
    slack_handle VARCHAR(100) NOT NULL,
    email VARCHAR(255),
    phone VARCHAR(20),
    role VARCHAR(50) DEFAULT 'primary', -- primary, secondary, tertiary
    is_active BOOLEAN DEFAULT TRUE,
    start_date TIMESTAMP,
    end_date TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Escalation policies
CREATE TABLE IF NOT EXISTS escalation_policies (
    id SERIAL PRIMARY KEY,
    service_name VARCHAR(255) NOT NULL,
    severity VARCHAR(10) NOT NULL, -- P0, P1, P2
    escalation_level INTEGER DEFAULT 1,
    engineer_name VARCHAR(255),
    slack_handle VARCHAR(100),
    email VARCHAR(255),
    phone VARCHAR(20),
    wait_time_minutes INTEGER DEFAULT 5,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Seed on-call data
INSERT INTO oncall_rotations (service_name, engineer_name, slack_handle, email, phone, role) VALUES
('payment-api', 'Rahul Kumar', '@rahul', 'rahul@razorpay.com', '+91-98765-43210', 'primary'),
('payment-api', 'Priya Singh', '@priya', 'priya@razorpay.com', '+91-87654-32109', 'secondary'),
('payment-api', 'Amit Patel', '@amit', 'amit@razorpay.com', '+91-76543-21098', 'tertiary'),
('auth', 'Sneha Reddy', '@sneha', 'sneha@razorpay.com', '+91-65432-10987', 'primary'),
('auth', 'Vikram Shah', '@vikram', 'vikram@razorpay.com', '+91-54321-09876', 'secondary'),
('ledger', 'Ananya Sharma', '@ananya', 'ananya@razorpay.com', '+91-43210-98765', 'primary'),
('ledger', 'Arjun Mehta', '@arjun', 'arjun@razorpay.com', '+91-32109-87654', 'secondary'),
('database', 'Shreya Gupta', '@shreya', 'shreya@razorpay.com', '+91-21098-76543', 'primary'),
('database', 'Manish Kumar', '@manish', 'manish@razorpay.com', '+91-10987-65432', 'secondary');

-- Seed escalation policies
INSERT INTO escalation_policies (service_name, severity, escalation_level, engineer_name, slack_handle, email, phone, wait_time_minutes) VALUES
('payment-api', 'P0', 1, 'Rahul Kumar', '@rahul', 'rahul@razorpay.com', '+91-98765-43210', 5),
('payment-api', 'P0', 2, 'Priya Singh', '@priya', 'priya@razorpay.com', '+91-87654-32109', 5),
('payment-api', 'P0', 3, 'Amit Patel', '@amit', 'amit@razorpay.com', '+91-76543-21098', 5),
('payment-api', 'P1', 1, 'Priya Singh', '@priya', 'priya@razorpay.com', '+91-87654-32109', 15),
('auth', 'P0', 1, 'Sneha Reddy', '@sneha', 'sneha@razorpay.com', '+91-65432-10987', 5),
('auth', 'P0', 2, 'Vikram Shah', '@vikram', 'vikram@razorpay.com', '+91-54321-09876', 10);
