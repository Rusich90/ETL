import logging.config
import time

from logger_config import LOGGING_CONFIG
from postgres_loader import PostgresLoader
from settings import settings
from state import State, Storage
from utils import parse_to_elastic, request_to_elastic


logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger('my_logger')


def load_data() -> None:
    """
    Основная функция скрипта для обновления записей в эластике
    :return: None
    """
    try:
        while True:
            """
            Берем актуальную дату апдейта из файла состояний, если нету даты, берем дату из конфигурации
            """
            storage = Storage(settings.pg_conf.state_file_path)
            state = State(storage)

            """
            Проходим по каждой таблицы из списка таблиц в конфиге
            """
            for table in settings.pg_conf.tables:
                pg_loader = PostgresLoader()
                date = state.get_state(table) if state.get_state(table) else settings.pg_conf.default_date

                """
                Проверяем есть ли обновления после даты из состояния
                """
                records_for_update = pg_loader.check_updates(table, date)
                if not records_for_update:
                    logger.info(f'No updates for {table} table')
                    continue
                """
                Запоминаем дату апдейта последней записи в списке
                """
                last_update_date = str(records_for_update[-1]['updated_at'])
                ids_list = tuple([record['id'] for record in records_for_update])

                if table == 'film_work':
                    """
                    Если проверяем таблицу с фильмами - то запрос к вспомогательной таблице не делаем
                    """
                    movies = pg_loader.load_movies(ids_list)
                    json_list = parse_to_elastic(movies)
                    request_to_elastic(json_list)
                else:
                    """
                    Запрос к вспомогательной таблице и запоминание оффсета для запроса пачками (зависит от query_limit)
                    """
                    offset = 0
                    while True:
                        movies_for_update = pg_loader.load_movies_ids(table, ids_list, offset)
                        if not movies_for_update:
                            break
                        movies_ids = tuple([movie['id'] for movie in movies_for_update])

                        movies = pg_loader.load_movies(movies_ids)
                        json_list = parse_to_elastic(movies)
                        request_to_elastic(json_list)

                        offset += pg_loader.limit

                """
                Устонавливаем дату в состояние после успешного запроса к эластику
                """
                state.set_state(table, last_update_date)

            pg_loader.close()
            time.sleep(5)
    except KeyboardInterrupt:
        logger.info("ETL process finished!")
    except:
        logger.error("Something goes wrong!")
    finally:
        pg_loader.close()
        logger.info('Connection with DB closed!')


if __name__ == '__main__':
    logger.info('ETL process started ')
    load_data()
