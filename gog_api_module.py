# -*- coding: utf-8 -*-
from __future__ import print_function
from __future__ import division
from __future__ import unicode_literals

# imports
import sys
import logging
import contextlib
import json
import html5lib
import time
import getpass
import argparse
import codecs
import datetime
import socket
import http.cookiejar as cookiejar
from http.client import BadStatusLine
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, HTTPError, URLError, build_opener, Request
import psycopg2
import requests
from bs4 import BeautifulSoup


# благодарим за возможность подключить GOG вот эту программу для скачивания игр
# https://github.com/eddie3/gogrepo


# заглушка
try:
    from html2text import html2text
except ImportError:
    def html2text(x):
        return x

# библа для обхода проверки куки
cookiejar.MozillaCookieJar.magic_re = r'.*'

# логгирование
logFormatter = logging.Formatter("%(asctime)s | %(message)s", datefmt='%H:%M:%S')
rootLogger = logging.getLogger('ws')
rootLogger.setLevel(logging.DEBUG)
consoleHandler = logging.StreamHandler(sys.stdout)
consoleHandler.setFormatter(logFormatter)
rootLogger.addHandler(consoleHandler)
info = rootLogger.info
warn = rootLogger.warning
debug = rootLogger.debug
error = rootLogger.error
log_exception = rootLogger.exception

# для работы web части
global_cookies = cookiejar.LWPCookieJar()
cookieproc = HTTPCookieProcessor(global_cookies)
opener = build_opener(cookieproc)
treebuilder = html5lib.treebuilders.getTreeBuilder('etree')
parser = html5lib.HTMLParser(tree=treebuilder, namespaceHTMLElements=False)

# GOG URLы
GOG_HOME_URL = r'https://www.gog.com'
GOG_ACCOUNT_URL = r'https://www.gog.com/account'
GOG_LOGIN_URL = r'https://login.gog.com/login_check'
GOG_API_URL = r'http://api.gog.com/products'

# Константы
GOG_MEDIA_TYPE_GAME = '1'
GOG_MEDIA_TYPE_MOVIE = '2'

# HTTP request settings
HTTP_FETCH_DELAY = 1
HTTP_RETRY_DELAY = 5
HTTP_RETRY_COUNT = 3
HTTP_PERM_ERRORCODES = (404, 403, 503)

# These file types don't have md5 data from GOG
SKIP_MD5_FILE_EXT = ['.txt', '.zip']


def request(url, args=None, byte_range=None, retries=HTTP_RETRY_COUNT, delay=HTTP_FETCH_DELAY):
    # web запросы с повторами
    _retry = False
    time.sleep(delay)

    try:
        if args is not None:
            enc_args = urlencode(args)
            enc_args = enc_args.encode('ascii')
        else:
            enc_args = None
        req = Request(url, data=enc_args)
        if byte_range is not None:
            req.add_header('Range', 'bytes=%d-%d' % byte_range)
        page = opener.open(req)
    except (HTTPError, URLError, socket.error, BadStatusLine) as e:
        if isinstance(e, HTTPError):
            if e.code in HTTP_PERM_ERRORCODES:
                warn('ошибка запроса: %s.', e)
                raise
        if retries > 0:
            _retry = True
        else:
            raise

        if _retry:
            warn('ошибка запроса: %s (%d попыток осталось) -- рестарт через %ds...' % (e, retries, HTTP_RETRY_DELAY))
            return request(url=url, args=args, byte_range=byte_range, retries=retries - 1, delay=HTTP_RETRY_DELAY)

    return contextlib.closing(page)


# --------------------------
# Дополнительные типы и функции
# --------------------------

class AttrDict(dict):
    def __init__(self, **kw):
        self.update(kw)

    def __getattr__(self, key):
        return self[key]

    def __setattr__(self, key, val):
        self[key] = val


def item_checkdb(search_id, gamesdb):
    for i in range(len(gamesdb)):
        if search_id == gamesdb[i].id:
            return i
    return None


def process_argv(argv):
    p1 = argparse.ArgumentParser(description='%s' % ('Вход в сервис GOG'))
    p1.add_argument('username', action='store', help='GOG login/email', nargs='?', default=None)
    p1.add_argument('password', action='store', help='GOG пароль', nargs='?', default=None)

    # парсит полученные аргументы, выкидывает ошибку по необходимости
    args = p1.parse_args(argv[1:])
    return args


# --------
# Команды
# --------

def cmd_login(user, passwd):
    # Логинимся в GOG
    login_data = {'user': user,
                  'passwd': passwd,
                  'auth_url': None,
                  'login_token': None,
                  'two_step_url': None,
                  'two_step_token': None,
                  'two_step_security_code': None,
                  'login_success': False,
                  }

    global_cookies.clear()

    # просим логин/пароль по необходимости
    if login_data['user'] is None:
        login_data['user'] = input("Логин: ")
    if login_data['passwd'] is None:
        login_data['passwd'] = getpass.getpass()

    info("попытка входа в систему как '{}' ...".format(login_data['user']))

    # получаем url входа
    with request(GOG_HOME_URL, delay=0) as page:
        etree = html5lib.parse(page, namespaceHTMLElements=False)
        for elm in etree.findall('.//script'):
            if elm.text is not None and 'GalaxyAccounts' in elm.text:
                login_data['auth_url'] = elm.text.split("'")[3]
                break

    # обрабатываем токен логина
    with request(login_data['auth_url'], delay=0) as page:
        etree = html5lib.parse(page, namespaceHTMLElements=False)
        # расстраиваемся, если получаем требование ввода капчи
        if len(etree.findall('.//div[@class="g-recaptcha form__recaptcha"]')) > 0:
            error("невозможно продолжить, GOG требует ввод reCAPTCHA")
            return
        for elm in etree.findall('.//input'):
            if elm.attrib['id'] == 'login__token':
                login_data['login_token'] = elm.attrib['value']
                break

    # пытаемся залогиниться и получаем запрос на двухэтапную авторизацию
    with request(GOG_LOGIN_URL, delay=0, args={'login[username]': login_data['user'],
                                               'login[password]': login_data['passwd'],
                                               'login[login]': '',
                                               'login[_token]': login_data['login_token']}) as page:
        etree = html5lib.parse(page, namespaceHTMLElements=False)
        if 'two_step' in page.geturl():
            login_data['two_step_url'] = page.geturl()
            for elm in etree.findall('.//input'):
                if elm.attrib['id'] == 'second_step_authentication__token':
                    login_data['two_step_token'] = elm.attrib['value']
                    break
        elif 'on_login_success' in page.geturl():
            login_data['login_success'] = True

    # проводим двухэтапную
    if login_data['two_step_url'] is not None:
        login_data['two_step_security_code'] = input("введите код двухэтапной авторизации: ")

        # отправляем код обратно
        with request(login_data['two_step_url'], delay=0,
                     args={'second_step_authentication[token][letter_1]': login_data['two_step_security_code'][0],
                           'second_step_authentication[token][letter_2]': login_data['two_step_security_code'][1],
                           'second_step_authentication[token][letter_3]': login_data['two_step_security_code'][2],
                           'second_step_authentication[token][letter_4]': login_data['two_step_security_code'][3],
                           'second_step_authentication[send]': "",
                           'second_step_authentication[_token]': login_data['two_step_token']}) as page:
            if 'on_login_success' in page.geturl():
                login_data['login_success'] = True

    # выводим результат
    if login_data['login_success']:
        info('вход выполнен')
    else:
        error('вход не выполнен, проверьте введённые данные')


def cmd_update():
    media_type = GOG_MEDIA_TYPE_GAME
    items = []
    i = 0

    api_url = GOG_ACCOUNT_URL
    api_url += "/getFilteredProducts"

    # получаем данные игр
    done = False
    info('подключение к базе')
    conn = psycopg2.connect(dbname='game_shelf', user='pacas', password='12345', host='127.0.0.1', port='5432', connect_timeout=5)
    cursor = conn.cursor()
    info('подключено')
    while not done:
        i += 1
        info('получение данных (страница %d)...' % i)

        url = api_url + "?" + urlencode({'mediaType': media_type,
                                         'sortBy': 'title',
                                         'page': str(i)})

        with request(url, delay=0) as data_request:
            reader = codecs.getreader("utf-8")
            try:
                json_data = json.load(reader(data_request))
            except ValueError:
                error('ошибка получения данных')
                cursor.close()
                conn.close()
                raise SystemExit(1)

            # парсим интересующие поля в словарь
            for item_json_data in json_data['products']:
                item = AttrDict()
                item.id = item_json_data['id']
                item.long_title = item_json_data['title']
                item.genre = item_json_data['category']
                item.image_url = item_json_data['image']
                item.store_url = item_json_data['url']

                if item.store_url[0:5] == '/game/':
                    check = 1
                    item.store_url = GOG_HOME_URL + item.store_url
                    response = requests.get(item.store_url)
                    soup = BeautifulSoup(response.text, 'html.parser')
                    full_list = soup.find_all(class_='details__content table__row-content')
                    found = str(full_list[3])
                    c = [i for i in range(len(found)) if found.startswith('}" href="/games?devpub=', i)]
                    a = found.find("eventLabel: 'Developer: ")
                    b = found.find("eventLabel: 'Publisher: ")
                    dev = str(found[a + 24:c[0] - 1])
                    pub = str(found[b + 24:c[1] - 1])

                    # проверяем существование разрабов, иначе создаём
                    cursor.execute("SELECT EXISTS(SELECT name FROM companies WHERE name = '" + dev + "')")
                    records = cursor.fetchall()
                    if str(records[0][0]) == 'False':
                        cursor.callproc('insert_company', [dev, None, None])

                    # проверяем существование издателей, иначе создаём
                    cursor.execute("SELECT EXISTS(SELECT name FROM companies WHERE name = '" + pub + "')")
                    records = cursor.fetchall()
                    if str(records[0][0]) == 'False':
                        cursor.callproc('insert_company', [pub, None, None])
                else:
                    check = 0

                # проверяем существование жанра, иначе создаём
                cursor.execute("SELECT EXISTS(SELECT name FROM genres WHERE name = '" + item.genre + "')")
                records = cursor.fetchall()
                # info('жанр существует - %s' % records[0][0])
                if str(records[0][0]) == 'False':
                    # info('добавляем жанр %s' % item.genre)
                    cursor.callproc('insert_genre', [item.genre, None])

                addapi_url = GOG_API_URL
                addapi_url += "/" + str(item.id) + "?expand=expanded_dlcs,description,screenshots,videos"
                try:
                    with request(addapi_url) as data_request:
                        reader = codecs.getreader("utf-8")
                        item_json_data_additional = json.load(reader(data_request))

                        item.release_date = item_json_data_additional['release_date']
                        item.description = item_json_data_additional['description']
                        item.description = item.description['lead']

                except Exception:
                    log_exception('error')

                # добавляем игру
                info('добавляем игру %s' % item.long_title)
                cursor.callproc('insert_game', [item.long_title, item.release_date, item.description, item.image_url[2:] + '.png'])
                gameid = cursor.fetchall()
                # info('%s - полученный id' % gameid[0][0])

                # соединяем игру и жанр
                cursor.callproc('attach_game_genre', [gameid[0][0], item.genre])

                # соединяем игру и платформу
                cursor.execute("SELECT id FROM platforms WHERE name = 'GOG.com'")
                gogid = cursor.fetchall()
                cursor.callproc('attach_game_platform', [gameid[0][0], gogid[0][0], item.store_url, str(item.id)])

                if check == 1:
                    # соединяем игру и разрабов
                    cursor.callproc('attach_game_developer', [gameid[0][0], dev])

                    # соединяем игру и издателей
                    cursor.callproc('attach_game_publisher', [gameid[0][0], pub])
                else:
                    cursor.callproc('attach_game_developer', [gameid[0][0], ''])
                    cursor.callproc('attach_game_publisher', [gameid[0][0], ''])

                items.append(item)
                cursor.execute("COMMIT;")

            if i >= json_data['totalPages']:
                done = True

    # сообщаем, если ничего нет
    if len(items) == 0:
        warn('ничего нет')
        return

    items_count = len(items)
    info('найдено %d игр %s' % (items_count, '!' * int(items_count / 100)))

    # закрываем соединение
    cursor.close()
    conn.close()

    '''
    Полезные ссылки:
        embed.gog.com/userData.json - инфа с id пользователя
        embed.gog.com/users/info/48628349971017?expand=friendStatus,wishlistStatus,blockedStatus
    '''


def main(args):
    stime = datetime.datetime.now()

    cmd_login(args.username, args.password)
    cmd_update()
    etime = datetime.datetime.now()
    info('--')
    info('общее время: %s' % (etime - stime))


if __name__ == "__main__":
    try:
        main(process_argv(sys.argv))
        info('выход...')
    except KeyboardInterrupt:
        info('выход...')
        sys.exit(1)
    except SystemExit:
        raise
    except:
        log_exception('ошибка...')
        sys.exit(1)
