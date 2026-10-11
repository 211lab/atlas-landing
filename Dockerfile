# Atlas landing background generator.
#
# Standard-library-only Python so the runtime stays small. The same image is
# used by the homepage seed init-container (to place the original artwork on the
# shared volume before first generation) and by the scheduled weather CronJob.
FROM python:3.12-alpine

WORKDIR /app

COPY generator/ /app/generator/
COPY seed/ /app/seed/

# Drop the bundled pip to keep the image minimal; the generator has no deps.
RUN rm -rf /usr/local/lib/python3.12/ensurepip \
    && rm -f /usr/local/bin/pip /usr/local/bin/pip3

CMD ["python3", "/app/generator/generate.py"]
