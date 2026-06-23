FROM postgres:16

# The env mirror can't pull the pgvector image (library/* only), so build pgvector
# from source onto postgres:16. Same PG major => pgdata volume stays compatible.
ARG PGVECTOR_VERSION=0.8.0
RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-server-dev-16 build-essential git ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && git clone --branch v${PGVECTOR_VERSION} https://github.com/pgvector/pgvector.git /tmp/pgvector \
 && make -C /tmp/pgvector install \
 && rm -rf /tmp/pgvector
