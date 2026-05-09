FROM node:18-alpine AS builder

WORKDIR /app

# Railway build context is repo root when Dockerfile path is frontend/Dockerfile.
COPY frontend/package*.json ./
RUN npm install

COPY frontend/ ./
RUN npm run build

FROM node:18-alpine AS runner

WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000

COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./.next/standalone
COPY --from=builder /app/.next/static ./.next/static

CMD ["node", ".next/standalone/server.js"]
