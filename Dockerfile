ARG PYTHON_VERSION=3.14
ARG GO_VERSION=1.26

FROM golang:${GO_VERSION}-bookworm AS go-builder
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY cmd ./cmd
COPY internal ./internal
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags="-s -w" -o /out/bangumikomga-core ./cmd/bangumikomga-core

FROM python:${PYTHON_VERSION} AS builder
WORKDIR /app
COPY install/requirements.txt install/requirements.txt
RUN pip3 install -r install/requirements.txt

FROM python:${PYTHON_VERSION}-slim
ARG PYTHON_VERSION
WORKDIR /app
COPY --from=builder /usr/local/lib/python${PYTHON_VERSION}/site-packages /usr/local/lib/python${PYTHON_VERSION}/site-packages
COPY . .
COPY --from=go-builder /out/bangumikomga-core /app/bin/bangumikomga-core
EXPOSE 15600
CMD [ "python3", "main.py"]
