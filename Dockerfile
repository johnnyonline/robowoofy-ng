FROM python:3.12

WORKDIR /robowoofy-ng

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

RUN curl -L https://foundry.paradigm.xyz | bash && \
    /root/.foundry/bin/foundryup && \
    ln -s /root/.foundry/bin/* /usr/local/bin/

# docker build -t robowoofy-ng . --no-cache
# docker run -it --rm --env-file .env -v $(pwd):/robowoofy-ng robowoofy-ng bash