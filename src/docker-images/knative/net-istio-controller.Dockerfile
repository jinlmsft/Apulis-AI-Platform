FROM golang:1.15.0 AS build
RUN mkdir -p /go/src/github.com/knative && git clone -b release-0.15 https://github.com/knative-sandbox/net-istio.git /go/src/github.com/knative/net-istio
WORKDIR /go/src/github.com/knative/net-istio/cmd
RUN cd controller && go build && cp ./controller /usr/local/bin

FROM debian:stable-slim
COPY --from=build /usr/local/bin/controller .
ENTRYPOINT ["./controller"]