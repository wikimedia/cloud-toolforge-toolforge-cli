FROM debian:bullseye
ARG DEBIAN_FRONTEND noninteractive

COPY bullseye-backports.list /etc/apt/sources.list.d/
RUN apt update -y \
    && apt install -y ca-certificates

COPY toolforge.list /etc/apt/sources.list.d/

RUN apt update -y \
    && apt install -y devscripts
COPY entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
