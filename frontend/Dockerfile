FROM node:20-alpine AS builder

WORKDIR /app

# Railway build context is repo root when Dockerfile path is frontend/Dockerfile.
COPY frontend/package*.json ./
RUN npm install

COPY frontend/ ./
RUN npm run build

FROM node:20-alpine AS runner

WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

# Standalone server resolves `/_next/static` relative to this tree — not repo-root `.next/static`.
COPY --from=builder /app/.next/standalone ./standalone
COPY --from=builder /app/.next/static ./standalone/.next/static
COPY --from=builder /app/public ./standalone/public

WORKDIR /app/standalone

CMD ["node", "server.js"]
