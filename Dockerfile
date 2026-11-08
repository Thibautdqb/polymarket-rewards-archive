FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
VOLUME /data
ENTRYPOINT ["pmrewards", "--db", "/data/rewards.db"]
CMD ["collect", "--every", "300", "--raw-dir", "/data/raw"]
