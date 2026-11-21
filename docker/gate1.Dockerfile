FROM alpine:3.23@sha256:469c9ea410b9215eaee7976ba6c0639039b444be8e5d638f7abbada189971eb2 AS trust
FROM ubuntu:26.04@sha256:d66b366dac61b575bee2aef07e9c26e8070096fbe84a3d4d3eb0da069b5d76db

# Bootstrap TLS for the signed Ubuntu snapshot before ca-certificates is installed.
COPY --from=trust /etc/ssl/certs/ca-certificates.crt /tmp/bootstrap-ca.crt
RUN sed -i -E 's#http://(archive|security)\.ubuntu\.com/ubuntu/#https://snapshot.ubuntu.com/ubuntu/20261105T000000Z/#; /Suites:/s/ resolute-backports//; /^Signed-By:/a Check-Valid-Until: no' /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get -o Acquire::https::CaInfo=/tmp/bootstrap-ca.crt -o Acquire::Retries=3 --error-on=any update \
    && DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::https::CaInfo=/tmp/bootstrap-ca.crt \
       -o Acquire::Retries=3 install -y --no-install-recommends \
       bubblewrap ca-certificates dbus-user-session g++-15 git libc6-dev libpam-systemd \
       poppler-utils python3 python3.14-venv systemd-sysv texlive-latex-extra texlive-publishers \
    && rm -rf /var/lib/apt/lists/* /tmp/bootstrap-ca.crt \
    && ln -s gcc-15 /usr/bin/gcc && ln -s g++-15 /usr/bin/g++ \
    && test "$(g++ -dumpfullversion)" = 15.2.0

COPY requirements-ast.txt /tmp/requirements-ast.txt
RUN python3.14 -m venv /opt/eapg \
    && /opt/eapg/bin/python -m pip install --no-cache-dir -r /tmp/requirements-ast.txt pytest==9.0.2 \
    && rm /tmp/requirements-ast.txt \
    && useradd --uid 1000 --create-home --shell /bin/bash eapg \
    && install -d -o eapg -g eapg /workspace \
    && install -d /etc/systemd/system/user@.service.d \
    && printf '[Service]\nDelegate=cpu cpuset io memory pids\n' >/etc/systemd/system/user@.service.d/delegate.conf

ENV container=docker PATH="/opt/eapg/bin:${PATH}"
WORKDIR /workspace
CMD ["/sbin/init"]
