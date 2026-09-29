FROM debian:bookworm-slim AS whisper-build

ARG WHISPER_CPP_REF=v1.9.4
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates cmake curl g++ git make && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch "${WHISPER_CPP_REF}" \
    https://github.com/ggml-org/whisper.cpp.git /src/whisper.cpp
RUN cmake -S /src/whisper.cpp -B /src/whisper.cpp/build \
    -DCMAKE_BUILD_TYPE=Release -DWHISPER_BUILD_TESTS=OFF -DGGML_NATIVE=OFF \
    && cmake --build /src/whisper.cpp/build --target whisper-cli -j 1
RUN cd /src/whisper.cpp && bash models/download-ggml-model.sh base

FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libgomp1 && rm -rf /var/lib/apt/lists/*
COPY --from=whisper-build /src/whisper.cpp/build /opt/whisper-build
COPY --from=whisper-build /src/whisper.cpp/models/ggml-base.bin /opt/models/ggml-base.bin
WORKDIR /app
COPY pyproject.toml /app/
COPY src /app/src
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin shopping \
    && mkdir -p /data /tmp/shopping \
    && chown -R shopping:shopping /data /tmp/shopping
USER shopping
ENV PYTHONPATH=/app/src \
    SHOPPING_DATA_DIR=/data \
    WHISPER_CLI=/opt/whisper-build/bin/whisper-cli \
    WHISPER_MODEL=/opt/models/ggml-base.bin \
    LD_LIBRARY_PATH=/opt/whisper-build/bin
CMD ["python", "-m", "shopping_bot.app"]
