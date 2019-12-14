# -*- coding: utf-8 -*-
import requests
import datetime
import progressbar
import logging
import sys
from steam import WebAPI
import psycopg2

# API key - для доступа к получению информации без боли
api = WebAPI(key="тут мог быть ваш апи ключ")

# логгинг
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


# тест на "вшивость" - игра ли перед нами
def additionaltest(steamid):
    URL = "https://store.steampowered.com/api/appdetails?appids=" + steamid
    data = requests.get(URL, timeout=10).json()
    a = data.get(steamid, dict()).get("data", dict())
    gtype = a.get('type', '')
    if gtype != 'game':
        a = 0
    else:
        a = 1
    return(a)


# получение расширенной информации по игре и обнаружение подозрительных игр с отправкой на тестирование
def idreader(SteamGameID):
    # получение более полной информации по игре
    URL1 = "http://steamspy.com/api.php?request=appdetails&appid=" + SteamGameID
    data = requests.get(URL1, timeout=10).json()

    # обработка полученной информации
    average_forever = data.get('average_forever', int())
    genres = data.get('genre', '')
    developer = data.get('developer', '')
    developer = developer.split(', ')
    publisher = data.get('publisher', '')
    publisher = publisher.split(', ')
    tags = data.get('tags', '')
    ccu = data.get('ccu', int())

    ToReturn = [genres, developer, publisher, tags]
    # первоначальная проверка, стоит ли отправлять на проверку на "вшивость"
    if average_forever == 0 and ccu == 0:
        if additionaltest(SteamGameID) == 0:
            genres = '0'
            broken.append(SteamGameID)
    # иначе добавляем жанры
    elif genres != '':
        pass
    else:
        genres = '-'
    return (ToReturn)


def DBPart(Name, Genres, Devs, Pubs, AppID, Logo, StoreURL):
    # проверяем существование разрабов, иначе создаём
    for dev in Devs:
        dev = dev.replace("'", '"')
        cursor.execute("SELECT EXISTS(SELECT name FROM companies WHERE name = '" + dev + "')")
        records = cursor.fetchall()
        if str(records[0][0]) == 'False':
            cursor.callproc('insert_company', [dev, None, None])

    # проверяем существование издателей, иначе создаём
    for pub in Pubs:
        pub = pub.replace("'", '"')
        cursor.execute("SELECT EXISTS(SELECT name FROM companies WHERE name = '" + pub + "')")
        records = cursor.fetchall()
        if str(records[0][0]) == 'False':
            cursor.callproc('insert_company', [pub, None, None])

    # добавляем игру
    Name = Name.replace("'", '"')
    cursor.callproc('insert_game', [Name, None, None, Logo])
    GameID = cursor.fetchall()

    # проверяем существование жанра, иначе создаём, соединяем игру и жанр
    for genre in Genres:
        cursor.execute("SELECT EXISTS(SELECT name FROM genres WHERE name = '" + genre + "')")
        records = cursor.fetchall()
        if str(records[0][0]) == 'False':
            cursor.callproc('insert_genre', [genre, None])
        cursor.callproc('attach_game_genre', [GameID[0][0], genre])

    # соединяем игру и платформу
    cursor.execute("SELECT id FROM platforms WHERE name = 'Steam'")
    SteamID = cursor.fetchall()
    cursor.callproc('attach_game_platform', [GameID[0][0], SteamID[0][0], StoreURL, AppID])

    # соединяем игру и разрабов
    for dev in Devs:
        cursor.callproc('attach_game_developer', [GameID[0][0], dev])

    # соединяем игру и издателей
    for pub in Pubs:
        cursor.callproc('attach_game_publisher', [GameID[0][0], pub])

    cursor.execute("COMMIT;")


# получение списка игр на аккаунте с вызовом получения инфы по каждой и табличкой
def homepage(SteamUserID):
    # метод для получения информации о имеющихся играх (пока что на webapi)
    data = api.call('IPlayerService.GetOwnedGames', steamid=SteamUserID, include_appinfo='1', include_played_free_games='1', appids_filter='')

    # начинаем дёргать инфу
    counter = 0
    data = data['response']
    games = data['games']
    gamecount = data['game_count']
    info('%s игр найдено' % gamecount)
    for game in progressbar.progressbar(games):
        counter += 1
        Name = game['name']
        Hours = int(game['playtime_forever']) // 60
        AppID = str(game['appid'])
        ImageHash = game['img_logo_url']
        AddInfo = idreader(AppID)
        # получение итоговых сведений от проверки на "вшивость"
        if AddInfo[0] == '0':
            counter -= 1
        else:
            # программы и музыка не пройдут
            if ('Utilities' not in AddInfo[0]) and ('Soundtrack' not in AddInfo[3]):
                Genres = AddInfo[0].split(', ')
                Logo = 'http://media.steampowered.com/steamcommunity/public/images/apps/' + AppID + '/' + ImageHash + '.jpg'
                StoreURL = 'https://store.steampowered.com/app/' + AppID
                DBPart(Name, Genres, AddInfo[1], AddInfo[2], AppID, Logo, StoreURL)
            else:
                counter -= 1


# тело, где идёт подсчёт времени
def main(args):
    stime = datetime.datetime.now()
    homepage(args[1])
    etime = datetime.datetime.now()
    info('--')
    info('общее время: %s' % (etime - stime))


# основа, подключение к базе и обработчик ошибок
if __name__ == "__main__":
    try:
        info('подключение к базе')
        conn = psycopg2.connect(dbname='game_shelf', user='pacas', password='12345', host='127.0.0.1', port='5432', connect_timeout=5)
        cursor = conn.cursor()
        info('подключено')
        broken = list()
        main(sys.argv)
        # info(broken)
        # закрываем соединение
        cursor.close()
        conn.close()
        info('выход')
    except KeyboardInterrupt:
        info('выход')
        sys.exit(1)
    except SystemExit:
        raise
    except:
        log_exception('ошибка...')
        sys.exit(1)

# 76561198150570906 - ваня
# 76561198248849448 - рандом
# 76561198053995688 - я
# 76561198097638050 - арбуз
