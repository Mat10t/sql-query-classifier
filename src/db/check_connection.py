import os

import psycopg
from dotenv import load_dotenv


def main():
    load_dotenv()

    connection_params = {
        "host": os.getenv("DB_HOST"),
        "port": os.getenv("DB_PORT"),
        "dbname": os.getenv("DB_NAME"),
        "user": os.getenv("DB_USER"),
        "password": os.getenv("DB_PASSWORD"),
    }

    try:
        with psycopg.connect(**connection_params) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT version();")
                version = cursor.fetchone()[0]
                print("Подключение успешно")
                print(version)

    except Exception as error:
        print("Ошибка подключения к PostgreSQL:")
        print(error)


if __name__ == "__main__":
    main()