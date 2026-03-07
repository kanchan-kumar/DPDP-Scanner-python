CREATE DATABASE IF NOT EXISTS dpdp_scanner_sample;
USE dpdp_scanner_sample;

CREATE TABLE IF NOT EXISTS customers (
    customer_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    full_name VARCHAR(150) NOT NULL,
    email VARCHAR(255) NOT NULL,
    phone VARCHAR(50),
    aadhaar VARCHAR(20),
    pan VARCHAR(20),
    postal_address TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_customers_email (email)
);

CREATE TABLE IF NOT EXISTS payments (
    payment_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    customer_id BIGINT NOT NULL,
    card_number VARCHAR(30),
    card_holder VARCHAR(150),
    bank_account VARCHAR(40),
    upi_id VARCHAR(150),
    billing_email VARCHAR(255),
    billing_phone VARCHAR(50),
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_payments_customer_billing_email (customer_id, billing_email),
    CONSTRAINT fk_payments_customer
        FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
);

CREATE TABLE IF NOT EXISTS employee_profiles (
    employee_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    employee_name VARCHAR(150) NOT NULL,
    employee_email VARCHAR(255),
    emergency_contact_phone VARCHAR(50),
    passport_number VARCHAR(30),
    ifsc_code VARCHAR(20),
    home_address TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_employee_profiles_email (employee_email)
);

INSERT INTO customers (full_name, email, phone, aadhaar, pan, postal_address)
VALUES
    ('Rahul Sharma', 'rahul.sharma@example.com', '+91-9876543210', '1234 5678 9012', 'ABCDE1234F', '22, MG Road, Bengaluru'),
    ('Aditi Verma', 'aditi.verma@example.in', '+91-9123456789', '4321 8765 2109', 'PQRSV4321K', '14, Park Street, Kolkata'),
    ('John Miller', 'john.miller@example.org', '+1-202-555-0186', NULL, NULL, '500 Elm Street, Springfield')
ON DUPLICATE KEY UPDATE
    full_name = VALUES(full_name),
    email = VALUES(email),
    phone = VALUES(phone),
    aadhaar = VALUES(aadhaar),
    pan = VALUES(pan),
    postal_address = VALUES(postal_address);

INSERT INTO payments (
    customer_id,
    card_number,
    card_holder,
    bank_account,
    upi_id,
    billing_email,
    billing_phone,
    notes
)
SELECT c.customer_id,
       '4111-1111-1111-1111',
       'Rahul Sharma',
       '1234567890123456',
       'rahul@okicici',
       'billing.rahul@example.com',
       '+91-9988776655',
       'Priority customer for refund processing'
FROM customers c WHERE c.email = 'rahul.sharma@example.com'
UNION ALL
SELECT c.customer_id,
       '5555-4444-3333-1111',
       'Aditi Verma',
       '9876543210987654',
       'aditi@oksbi',
       'billing.aditi@example.in',
       '+91-9090909090',
       'KYC completed with PAN and address proof'
FROM customers c WHERE c.email = 'aditi.verma@example.in'
ON DUPLICATE KEY UPDATE
    card_number = VALUES(card_number),
    card_holder = VALUES(card_holder),
    bank_account = VALUES(bank_account),
    upi_id = VALUES(upi_id),
    billing_phone = VALUES(billing_phone),
    notes = VALUES(notes);

INSERT INTO employee_profiles (
    employee_name,
    employee_email,
    emergency_contact_phone,
    passport_number,
    ifsc_code,
    home_address
)
VALUES
    ('Nitin Rao', 'nitin.rao@company.com', '+91-9000011111', 'M1234567', 'HDFC0001234', '10 Residency Road, Pune'),
    ('Sana Khan', 'sana.khan@company.com', '+91-9888877777', 'L7654321', 'ICIC0005678', '44 Linking Road, Mumbai')
ON DUPLICATE KEY UPDATE
    employee_email = VALUES(employee_email),
    emergency_contact_phone = VALUES(emergency_contact_phone),
    passport_number = VALUES(passport_number),
    ifsc_code = VALUES(ifsc_code),
    home_address = VALUES(home_address);
