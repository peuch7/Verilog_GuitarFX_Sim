# The reference environment for this project, and the supported route on Windows.
#
# Everything comes from apt, so this builds natively on Apple Silicon and on x86
# with no emulation and no per-machine differences.
#
# The repository is bind-mounted at /work rather than copied in. That keeps the
# image independent of the source (it only rebuilds when this file changes), and
# means edits on the host take effect immediately inside the container, with
# output wav files landing on the host where they can be played.
FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        verilator \
        iverilog \
        build-essential \
        git \
        make \
        python3 \
        python3-numpy \
        python3-scipy \
        python3-matplotlib \
        python3-pytest \
    && rm -rf /var/lib/apt/lists/*

# Import wavsim straight from the bind mount, so there is no installed copy that
# can go stale against the source.
ENV PYTHONPATH=/work/tools

# Same entry point as a native install, so every command in the docs works
# identically inside and outside the container.
RUN printf '#!/bin/sh\nexec python3 -m wavsim "$@"\n' > /usr/local/bin/wavsim \
    && chmod +x /usr/local/bin/wavsim

WORKDIR /work
CMD ["bash"]
