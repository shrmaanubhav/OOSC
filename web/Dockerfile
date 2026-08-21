# Project Sentinel -- dashboard (Next.js 15). Multi-stage standalone
# build: deps -> build -> minimal runtime image (no full node_modules).
#
# NEXT_PUBLIC_API_BASE is a build-time value (Next.js inlines
# NEXT_PUBLIC_* vars into the client bundle at build, not at container
# start) -- override it with `docker compose build --build-arg` or
# `docker build --build-arg NEXT_PUBLIC_API_BASE=...` if the API isn't
# reachable at the default http://localhost:8000 from the browser.

FROM node:22-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-slim AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ARG NEXT_PUBLIC_API_BASE=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE
RUN npm run build

FROM node:22-slim AS runtime
RUN groupadd -r sentinel && useradd -r -g sentinel sentinel
WORKDIR /app
ENV NODE_ENV=production PORT=3000 HOSTNAME=0.0.0.0

# Standalone output: a self-contained server.js + only the node_modules
# it actually traced as needed, not the full dev node_modules tree.
COPY --from=builder /app/public ./public
COPY --from=builder --chown=sentinel:sentinel /app/.next/standalone ./
COPY --from=builder --chown=sentinel:sentinel /app/.next/static ./.next/static

USER sentinel
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD node -e "fetch('http://127.0.0.1:3000').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "server.js"]
