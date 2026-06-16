# Kitium base image.
#
# `kicad-cli pcb import` (Altium) requires KiCad 10 — it does NOT exist in the 9.0
# CLI, and the inti-cmnb KiBot images only go up to KiCad 8. So we build on the
# OFFICIAL kicad/kicad image (which has `kicad-cli pcb import`) and add KiBot via pip.
#
# Pin a concrete patch tag for reproducibility, and AVOID 10.0.1 — it has a
# kicad-cli render/STEP regression that drops component 3D models. Phase 0 confirms
# the exact good tag and adds any system deps KiBot needs for our outputs.
ARG KICAD_IMAGE=kicad/kicad:10.0.0
FROM ${KICAD_IMAGE}

LABEL org.opencontainers.image.title="Kitium" \
      org.opencontainers.image.description="Altium -> KiCad CI validation gate" \
      org.opencontainers.image.source="https://github.com/Cimos/kitium"

USER root
# KiBot is a pip package layered on top of KiCad. Debian (bookworm+) marks the
# system Python externally-managed (PEP 668), hence --break-system-packages.
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3-pip git \
 && rm -rf /var/lib/apt/lists/* \
 && pip3 install --no-cache-dir --break-system-packages kibot

# Scripts otherwise use only the Python 3 stdlib + tools already in the image.
COPY scripts/ /opt/kitium/scripts/
COPY kibot/   /opt/kitium/kibot/
RUN chmod +x /opt/kitium/scripts/*.sh

ENV KITIUM_HOME=/opt/kitium
ENTRYPOINT ["/opt/kitium/scripts/entrypoint.sh"]
