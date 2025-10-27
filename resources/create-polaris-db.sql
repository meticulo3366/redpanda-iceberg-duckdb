-- Initialize Polaris database and user
-- Use conditional logic to avoid errors if database/user already exists

-- Create polaris user if it doesn't exist
DO
$$
BEGIN
   IF NOT EXISTS (SELECT FROM pg_user WHERE usename = 'polaris') THEN
      CREATE USER polaris WITH PASSWORD 'polaris123';
   END IF;
END
$$;

-- Grant connect permission (safe to run multiple times)
GRANT CONNECT ON DATABASE polaris TO polaris;

-- Connect to polaris database
\c polaris

-- Create schema if it doesn't exist
CREATE SCHEMA IF NOT EXISTS polaris AUTHORIZATION polaris;

-- Grant privileges (safe to run multiple times)
GRANT ALL PRIVILEGES ON SCHEMA polaris TO polaris;
GRANT ALL ON DATABASE polaris TO polaris;
