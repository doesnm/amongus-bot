FROM 3.14.8-alpine3.23
COPY --from=ghcr.io/astral-sh/uv:alpine3.23 /uv /uvx /bin/

WORKDIR /usr/app

COPY . ./
RUN uv sync --locked

CMD ["uv", "run", "amongus-bot"]
