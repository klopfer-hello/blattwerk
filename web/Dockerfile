# Web UI: build with Node, serve the static files with unprivileged nginx.
FROM node:24.22.0-slim AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
ARG VERSION=dev
RUN npm run build && echo "$VERSION" > dist/version.txt

# 13 days old when taken (2026-11-01): early, for the HIGH fix CVE-2026-15176. Pinned by digest.
FROM nginxinc/nginx-unprivileged:1.31.7-alpine@sha256:b5047b9b76845eac124358373c6852377c52e4b05834a47647e955dd91cb8f1e
USER root
RUN apk upgrade --no-cache  # the distribution's security fixes since the base image was built (CI: Trivy)
USER 101
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY security-headers.conf /etc/nginx/security-headers.conf
COPY --from=build /src/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -qO- http://127.0.0.1:8080/healthz >/dev/null || exit 1
