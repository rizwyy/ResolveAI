FROM node:22.14.0-alpine AS build
WORKDIR /workspace
COPY package.json package-lock.json ./
COPY apps/web/package.json apps/web/package.json
RUN npm ci
COPY apps/web apps/web
RUN npm --workspace @resolveai/web run generate

FROM nginx:1.27-alpine
COPY --from=build /workspace/apps/web/.output/public /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
