# The proxy container (backend design §8): Node builds the React application, and the built files go into a Caddy
# image with deploy/Caddyfile. No Node at run time. Built from the repository root, as platform/docker-compose.yml
# does, because the type check reads the example responses in backend/fixtures/ and the Caddyfile lives in deploy/:
#
#   docker build -f frontend/Dockerfile -t kg-proxy .
FROM node:22.23.5-alpine@sha256:1314fb30ec37592d5845e5a160d522c0e680972aa534549940b8d73bde88481a AS build
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
COPY backend/fixtures/ /src/backend/fixtures/
RUN npm run build

FROM caddy:2.11.9-alpine@sha256:003a97808e781aa9f7e75cc2f43d34d461099031faf5e20faefb9f61126836f0
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /src/frontend/dist /srv/frontend
