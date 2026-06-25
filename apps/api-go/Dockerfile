FROM golang:1.23-alpine AS build

WORKDIR /src

COPY apps/api-go/go.mod ./apps/api-go/go.mod
WORKDIR /src/apps/api-go
RUN go mod download

WORKDIR /src
COPY apps/api-go ./apps/api-go
WORKDIR /src/apps/api-go
RUN CGO_ENABLED=0 GOOS=linux go build -o /out/pea-api-intellisense ./cmd/pea-api-intellisense

FROM alpine:3.20

RUN adduser -D -H peaapi
USER peaapi

ENV PORT=8090 \
    AIS_NOTIFICATION_MODE=shadow \
    RATE_LIMIT_PER_MINUTE=120

EXPOSE 8090

COPY --from=build /out/pea-api-intellisense /pea-api-intellisense

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -qO- "http://127.0.0.1:${PORT}/health" | grep -q '"production_send":"blocked"'

CMD ["/pea-api-intellisense"]
