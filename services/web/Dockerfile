# syntax=docker/dockerfile:1
# Интерфейс: сборка React (Vite) → статические файлы в nginx (без root, порт 8080).
# Конфиг nginx не в образе: ConfigMap web-nginx чарта (values: web.nginxConf).
FROM node:22.23.3-alpine3.24 AS build
WORKDIR /web
COPY services/web/package.json services/web/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY services/web/ ./
RUN npm run build

FROM nginx:1.30.5-alpine
COPY --from=build /web/dist /usr/share/nginx/html
RUN sed -i 's#^pid .*#pid /tmp/nginx.pid;#' /etc/nginx/nginx.conf \
    && rm -f /etc/nginx/conf.d/default.conf \
    && chown -R nginx:nginx /var/cache/nginx /usr/share/nginx/html
USER nginx
EXPOSE 8080
