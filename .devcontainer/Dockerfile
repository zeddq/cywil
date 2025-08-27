FROM python:3.11-slim-bookworm
ENV DEBIAN_FRONTEND=noninteractive

# (Optional) print UTC clock for debugging
RUN date -u

# Temporarily ignore repo "not valid yet" timestamps
RUN printf 'Acquire::Check-Valid-Until "false";\nAcquire::Check-Date "false";\n' \
  > /etc/apt/apt.conf.d/99-no-date-check \
  && apt-get update \
  && apt-get install -y --no-install-recommends \
  xvfb xauth libx11-6 libxext6 libxrender1 libxtst6 \
  git curl gcc g++ make libpq-dev wget tmux jujutsu gh cron \
  && rm -rf /var/lib/apt/lists/*

RUN service cron start || /etc/init.d/cron start || true

RUN useradd -m -u 1000 agent
WORKDIR /home/agent
