# Use Bun image
FROM oven/bun:1 as base
WORKDIR /app

# Install dependencies
FROM base AS install
RUN mkdir -p /temp/dev
COPY package.json bun.lock /temp/dev/
RUN cd /temp/dev && bun install --frozen-lockfile

# Build the app
FROM base AS build
COPY --from=install /temp/dev/node_modules node_modules
COPY . .

# Client bundle talks to the same origin; Next rewrites /api/v1 to the backend.
# No key of any kind is declared here on purpose (PHASE-03/109): a NEXT_PUBLIC_*
# variable is inlined into the JavaScript, so a key set at build time would ship
# to every tab. The browser authenticates with a session cookie instead.
ENV NEXT_PUBLIC_API_URL=/api/v1
ENV API_PROXY_TARGET=http://backend:8000
RUN bun run build

# Production image
FROM base AS release
COPY --from=build /app/.next ./.next
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/package.json ./package.json
COPY --from=build /app/public ./public

# Expose port
EXPOSE 3000

# Start the app
CMD ["bun", "run", "start"]
