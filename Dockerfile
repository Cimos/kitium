# Kitium base image.
#
# We build on INTI-CMNB's KiCad automation images, which already bundle
# KiCad + KiBot + KiAuto + Xvfb. KiBot is just a layer on top of whatever
# KiCad is installed, so this is the cheapest path to a working container.
#
# NOTE: default is KiCad 9 (known-good, battle-tested in CI). The project
# *targets* KiCad 10 — Phase 0 will confirm `kicad10_auto_full` works with the
# current KiBot release; bump the default below once verified.
ARG KICAD_IMAGE=ghcr.io/inti-cmnb/kicad9_auto_full:latest
FROM ${KICAD_IMAGE}

LABEL org.opencontainers.image.title="Kitium" \
      org.opencontainers.image.description="Altium -> KiCad CI validation gate" \
      org.opencontainers.image.source="https://github.com/Cimos/kitium"

# Scripts only use the Python 3 stdlib + tools already in the base image,
# so there are no extra package installs to keep the image lean.
COPY scripts/ /opt/kitium/scripts/
COPY kibot/   /opt/kitium/kibot/
RUN chmod +x /opt/kitium/scripts/*.sh

ENV KITIUM_HOME=/opt/kitium
ENTRYPOINT ["/opt/kitium/scripts/entrypoint.sh"]
