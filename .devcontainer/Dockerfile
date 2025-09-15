ARG PYTHON_VERSION=3.11
FROM python:${PYTHON_VERSION}-slim-bookworm

# Avoid interactive tzdata prompts
ENV DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_SYSTEM_PYTHON=1

# Base OS deps for building common Python wheels and using git/tools
RUN --mount=type=cache,target=/var/cache/apt \
    apt-get update && apt-get install -y --no-install-recommends \
      git curl ca-certificates build-essential pkg-config \
      libffi-dev libssl-dev libpq-dev libsqlite3-dev \
      bash-completion less vim direnv \
    && rm -rf /var/lib/apt/lists/*

# Install uv (fast Python package manager) and pipx
# See: https://docs.astral.sh/uv/guides/integration/docker/
RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && python -m pip install --upgrade pip pipx \
    && python -m pipx ensurepath

# Optional: Poetry via pipx (pin to avoid surprise upgrades)
# See Poetry docs and community Docker guidance
RUN pipx install "poetry==1.8.3"
# Optional: pre-commit for repo hooks
RUN pipx install pre-commit

# Create non-root user matching VS Code devcontainers convention
ARG USERNAME=vscode
ARG UID=1000
ARG GID=1000
RUN groupadd --gid ${GID} ${USERNAME} \
    && useradd -s /bin/bash --uid ${UID} --gid ${GID} -m ${USERNAME} \
    && usermod -aG sudo ${USERNAME} || true

# direnv enablement for login shells
RUN echo 'eval "$(direnv hook bash)"' >> /etc/bash.bashrc

# Devcontainer defaults
WORKDIR /workspaces

# Copy project metadata first to leverage build cache during installs
# If you use uv: pyproject.toml + uv.lock
# If you use Poetry: pyproject.toml + poetry.lock
COPY pyproject.toml* uv.lock* poetry.lock* /tmp/app/
# Install deps into system Python (dev workflow; adjust for venv if desired)
# Prefer uv when lockfile present; fall back to Poetry export + pip
RUN --mount=type=cache,target=/root/.cache \
    if [ -f /tmp/app/uv.lock ]; then \
        /root/.local/bin/uv pip install -r /tmp/app/uv.lock; \
    elif [ -f /tmp/app/pyproject.toml ]; then \
        /root/.local/bin/pipx run --spec "poetry==1.8.3" \
          poetry export --with dev --format requirements.txt -o /tmp/req.txt \
        && python -m pip install -r /tmp/req.txt; \
    fi

# Claude Code hook scripts will live inside the repo; ensure executable bit works
# You can mount the repo at runtime; no copy needed here.

# Environment files used by your orchestrator hooks:
# .claude/.agent.env is read by sub-agents or sourced into Bash (your hook writes it).
# Keep a conventional path visible inside the container.
VOLUME ["/workspaces"]

# Minimal health and tool visibility
ENV PATH="/root/.local/bin:/root/.cargo/bin:/usr/local/bin:/usr/bin:/bin:${PATH}"

USER ${USERNAME}

# Helpful defaults inside the devcontainer
# (devcontainers will override entrypoint/cmd; keep this simple)
CMD ["bash"]
