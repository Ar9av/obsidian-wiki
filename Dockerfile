# Memory service: one container, one vault on a mounted volume.
# Build: docker build -t obsidian-wiki .
# Run:   docker run -p 8080:8080 -e WIKI_API_KEY=... -v wiki-data:/vault obsidian-wiki
FROM python:3.12-slim

# git: obsidian_wiki/sync.py shells out to it for vault backup.
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY . .
# .git is excluded from the build context, so hatch-vcs cannot read the tag.
# CI passes the real one: docker build --build-arg VERSION=2026.8.1
ARG VERSION=0.0.0
ENV HATCH_VCS_PRETEND_VERSION=$VERSION SETUPTOOLS_SCM_PRETEND_VERSION=$VERSION
RUN pip install --no-cache-dir '.[server]'

RUN useradd --create-home wiki && mkdir -p /vault && chown wiki:wiki /vault
USER wiki

ENV OBSIDIAN_VAULT_PATH=/vault WIKI_PORT=8080
VOLUME /vault
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health').status==200 else 1)"

CMD ["python", "-m", "obsidian_wiki.server"]
