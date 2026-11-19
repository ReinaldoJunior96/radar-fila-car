FROM node:24-alpine AS leaflet-assets
WORKDIR /build
RUN npm install --no-save leaflet@1.9.4

FROM nginx:alpine
RUN rm -f /etc/nginx/conf.d/default.conf && mkdir -p /var/cache/nginx/api
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
ENV EMBED_ORIGINS="'self'"
COPY index.html embed-radar.html app.css app.js radar.css radar.js assistente.js conhecimento.js nav.js /usr/share/nginx/html/
COPY --from=leaflet-assets /build/node_modules/leaflet/dist/leaflet.css /usr/share/nginx/html/vendor/leaflet.css
COPY --from=leaflet-assets /build/node_modules/leaflet/dist/leaflet.js /usr/share/nginx/html/vendor/leaflet.js
COPY --from=leaflet-assets /build/node_modules/leaflet/dist/images/ /usr/share/nginx/html/vendor/images/
