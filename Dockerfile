# Multi-Arch Lightweight Knowledge Portal Container
FROM python:3.11-alpine

WORKDIR /app

# Install package dependencies
COPY pyproject.toml .
COPY knowledge_portal knowledge_portal
COPY template template

RUN pip install --no-cache-dir .

# Non-root user for container security
RUN adduser -D -u 1000 portaluser && \
    chown -R portaluser:portaluser /app

USER portaluser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/dashboard.html')" || exit 1

ENTRYPOINT ["knowledge-portal"]
CMD ["serve", "--port", "8000", "--host", "0.0.0.0", "--dir", "."]
