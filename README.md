# robowoofy-ng

## Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/johnnyonline/robowoofy-ng.git
   cd robowoofy-ng
   ```

2. **Set up virtual environment**
   ```bash
   uv venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   # Install all dependencies
   uv sync
   ```

   > Note: This project uses [uv](https://github.com/astral-sh/uv) for faster dependency installation. If you don't have uv installed, you can install it with `pip install uv` or follow the [installation instructions](https://github.com/astral-sh/uv#installation).

4. **Environment setup**
   ```bash
   cp .env.example .env
   # Edit .env with your API keys and configuration

   # Load environment variables into your shell session
   export $(grep -v '^#' .env | xargs)
   ```

## Usage

Run:
```shell
brownie run src/woof.py woofy --network eth
```

## Code Style

Format and lint code with ruff:
```bash
# Format code
uv run ruff format .

# Lint code
uv run ruff check .

# Fix fixable lint issues
uv run ruff check --fix .
```

Type checking with mypy:
```bash
mypy src
```