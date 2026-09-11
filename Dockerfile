FROM debian:12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      sane-airscan \
      sane-utils \
      curl \
      img2pdf \
      python3 \
      python3-flask \
      gosu \
      tzdata \
      ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN echo airscan >> /etc/sane.d/dll.conf

COPY entrypoint.sh watch.sh app.py /app/
RUN chmod +x /app/entrypoint.sh /app/watch.sh

WORKDIR /app
EXPOSE 8080

ENV SCANNER_IP="" \
    PUID=1000 \
    PGID=1000 \
    TZ=UTC

ENTRYPOINT ["/app/entrypoint.sh"]
