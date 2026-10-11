# Atlas landing background generator.
#
# Pillow is needed to strip the letterbox bars the image model tends to add
# and to write a real JPEG; everything else is standard library. The same
# image is used by the homepage seed init-container (to place the original
# artwork on the shared volume before first generation) and by the scheduled
# weather CronJob.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt \
    && rm -rf /root/.cache

COPY generator/ /app/generator/
COPY seed/ /app/seed/

CMD ["python3", "/app/generator/generate.py"]
