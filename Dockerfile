# Atlas landing background generator.
#
# Pillow is needed to strip the letterbox bars the image model tends to add
# and to write a real JPEG; everything else is standard library. The same
# image is used by the homepage seed init-container (to place the original
# artwork on the shared volume before first generation) and by the scheduled
# weather CronJob.
FROM python:3.12-slim

WORKDIR /app

COPY generator/ /app/generator/
COPY seed/ /app/seed/

RUN pip install --no-cache-dir pillow==11.3.0 \
    && rm -rf /root/.cache

CMD ["python3", "/app/generator/generate.py"]
