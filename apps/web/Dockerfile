FROM node:22-alpine AS base
RUN corepack enable
WORKDIR /app

FROM base AS dependencies
COPY package.json ./
RUN pnpm install --frozen-lockfile=false

FROM base AS builder
ARG INTERNAL_API_BASE_URL=http://api:8000
ARG NEXT_PUBLIC_REQUIRE_INVITE=false
ARG NEXT_PUBLIC_API_BASE_URL=
ENV INTERNAL_API_BASE_URL=${INTERNAL_API_BASE_URL}
ENV NEXT_PUBLIC_REQUIRE_INVITE=${NEXT_PUBLIC_REQUIRE_INVITE}
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
COPY --from=dependencies /app/node_modules ./node_modules
COPY . .
RUN pnpm build

FROM base AS runner
ENV NODE_ENV=production
RUN addgroup --system --gid 1001 nodejs && adduser --system --uid 1001 nextjs
COPY --from=dependencies /app/node_modules ./node_modules
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY package.json ./
RUN chown -R nextjs:nodejs /app
USER nextjs
EXPOSE 3000
ENV PORT=3000
ENV HOSTNAME=0.0.0.0
CMD ["pnpm", "start"]
