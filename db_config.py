import os


REQUIRED_DB_ENV_VARS = ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD", "DB_PORT")


def get_missing_db_env_vars():
    return [name for name in REQUIRED_DB_ENV_VARS if not os.getenv(name)]


def build_db_config():
    missing = get_missing_db_env_vars()
    if missing:
        raise ValueError(f"Missing required database environment variables: {', '.join(missing)}")

    return {
        "host": os.getenv("DB_HOST"),
        "database": os.getenv("DB_NAME"),
        "user": os.getenv("DB_USER"),
        "password": os.getenv("DB_PASSWORD"),
        "port": os.getenv("DB_PORT"),
        "sslmode": "require",
        "connect_timeout": 10,
    }
