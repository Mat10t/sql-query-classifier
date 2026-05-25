import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv


TABLES = [
    "region",
    "nation",
    "supplier",
    "customer",
    "part",
    "partsupp",
    "orders",
    "lineitem",
]


def get_connection():
    load_dotenv()

    return psycopg.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )


def run_sql_file(connection, path: str):
    sql = Path(path).read_text(encoding="utf-8")

    with connection.cursor() as cursor:
        cursor.execute(sql)

    connection.commit()


def import_table(connection, table_name: str):
    tbl_path = Path("data/raw/tpch") / f"{table_name}.tbl"

    if not tbl_path.exists():
        raise FileNotFoundError(f"Файл не найден: {tbl_path}")

    print(f"Importing {table_name}...")

    with connection.cursor() as cursor:
        with cursor.copy(
            f"COPY {table_name} FROM STDIN WITH (FORMAT CSV, DELIMITER '|')"
        ) as copy:
            with tbl_path.open("r", encoding="utf-8") as file:
                for line in file:
                    line = line.rstrip("\n")

                    # dbgen добавляет лишний символ | в конце каждой строки.
                    # PostgreSQL COPY воспринимает его как лишний пустой столбец,
                    # поэтому удаляем последний разделитель.
                    if line.endswith("|"):
                        line = line[:-1]

                    copy.write(line + "\n")

    connection.commit()
    print(f"Imported {table_name}")


def analyze_tables(connection):
    with connection.cursor() as cursor:
        cursor.execute("ANALYZE;")

    connection.commit()
    print("ANALYZE completed")


def main():
    with get_connection() as connection:
        print("Creating TPC-H schema...")
        run_sql_file(connection, "src/db/create_tpch_schema.sql")

        for table_name in TABLES:
            import_table(connection, table_name)

        analyze_tables(connection)

    print("TPC-H import completed")


if __name__ == "__main__":
    main()
