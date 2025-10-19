FROM python:3.12

RUN pip install uv

WORKDIR /robowoofy-ng

COPY pyproject.toml ./

RUN uv sync --python /usr/local/bin/python

ENV PATH="/robowoofy-ng/.venv/bin:$PATH"

# `brownie-safe==0.9.0` has conflicting dependencies with `eth-brownie==1.21.0`, so using wavey's fork
RUN pip install eth-brownie==1.21.0 git+https://github.com/wavey0x/brownie-safe.git@deps setuptools==80.9.0

RUN curl -L https://foundry.paradigm.xyz | bash && \
    /root/.foundry/bin/foundryup && \
    ln -s /root/.foundry/bin/* /usr/local/bin/

# docker build -t robowoofy-ng . --no-cache
# docker run -it --rm -v $(pwd):/robowoofy-ng robowoofy-ng bash