FROM ghcr.io/astral-sh/uv:debian

# ffmpeg for voice/audio, required by discord-py[voice]
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY . .
RUN uv sync --frozen --no-dev

ENV DOCKER=1
CMD ["uv", "run", "--no-dev", "python", "main.py"]
