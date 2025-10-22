FROM ubuntu:22.04

# Install dependencies including Python, socat for port forwarding, and netcat for port checking
RUN apt-get update && apt-get install -y \
    wget \
    unzip \
    ca-certificates \
    python3 \
    python3-pip \
    socat \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# Download and install DuckDB CLI
RUN wget https://github.com/duckdb/duckdb/releases/latest/download/duckdb_cli-linux-amd64.zip && \
    unzip duckdb_cli-linux-amd64.zip && \
    mv duckdb /usr/local/bin/ && \
    chmod +x /usr/local/bin/duckdb && \
    rm duckdb_cli-linux-amd64.zip

# Install Python packages for DuckDB and Kafka integration
RUN pip3 install --no-cache-dir \
    duckdb==0.10.0 \
    confluent-kafka==2.3.0

WORKDIR /workspace

# Keep container running
CMD ["/bin/sh", "-c", "tail -f /dev/null"]
