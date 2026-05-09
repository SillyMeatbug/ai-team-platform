FROM node:20-alpine AS builder

WORKDIR /app

# Railway build context is repo root when Dockerfile path is frontend/Dockerfile.
COPY frontend/package*.json ./
RUN npm install

COPY frontend/ ./

# NEXT_PUBLIC_* попадает в клиентский бандл только на этапе build.
# В Railway задай переменную NEXT_PUBLIC_API_URL на сервисе фронта и сделай Redeploy.
ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_API_BASE_URL
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}

# Лог для отладки bake NEXT_PUBLIC_* (клиентский бандл). Публичный URL также можно задать только на runtime: BACKEND_PUBLIC_URL — см. app/layout.tsx.
RUN node -e "const u=(process.env.NEXT_PUBLIC_API_URL||'').trim();const b=(process.env.NEXT_PUBLIC_API_BASE_URL||'').trim();console.log('[docker build] NEXT_PUBLIC_API_URL len='+u.length+' BASE len='+b.length);const pick=u||b;if(!pick){console.warn('[docker build] NEXT_PUBLIC_* пуст — ок, если на Railway задан BACKEND_PUBLIC_URL (runtime).');}else if(/127\\.0\\.0\\.1|localhost/i.test(pick)){console.warn('[docker build] предупреждение: в NEXT_PUBLIC_* localhost:',pick);}else if(!/^https:\\/\\//i.test(pick)){console.warn('[docker build] ожидался https:',pick);}"

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
