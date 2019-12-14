# -*- coding: utf-8 -*-
import requests
import sys
import psycopg2

# получение расширенной информации по игре и обнаружение подозрительных игр с отправкой на тестирование
def idreader(SteamGameID):
    SteamGameID = SteamGameID[1]
    monthconventer = {
    'янв.' : '01',
    'фев.' : '02',
    'мар.' : '03',
    'апр.' : '04',
    'мая.' : '05',
    'июн.' : '06',
    'июл.' : '07',
    'авг.' : '08',
    'сен.' : '09',
    'окт.' : '10',
    'ноя.' : '11',
    'дек.' : '12'}
    # получение более полной информации по игре
    URL = "https://store.steampowered.com/api/appdetails?appids=" + SteamGameID + "&l=russian"
    data = requests.get(URL, timeout=10).json()
    data = data[SteamGameID]
    if data['success'] == False:
        check = 0
    else:
        data = data['data']
        # обработка полученной информации
        name = data.get('name', '')
        description = data.get('short_description', '')
        release_date = data.get('release_date', '') # ОТРАБОТКУ ДАТЫ
        
        if release_date['coming_soon'] != True:
            release_date = release_date['date']
            month = release_date[-9:-5]
            month = monthconventer[month]
            day = release_date[:-10]
            year = release_date[-4:]
            release_date = year + '-' + month + '-' + day

        else:
            release_date = '0001-01-01'
        
        check = 1

    if check == 1:
        DBPart(name, release_date, description)
    else:
        DBPart(None, None, None)

def DBPart(name, releasedate, description):
    cursor.execute("UPDATE games SET releasedate = '" + releasedate + "', description= '" + description + "' WHERE name = '" + name + "'")
    cursor.execute("COMMIT;")


# основа, подключение к базе и обработчик ошибок
if __name__ == "__main__":
    try:
        conn = psycopg2.connect(dbname='game_shelf', user='pacas', password='12345', host='127.0.0.1', port='5432', connect_timeout=5)
        cursor = conn.cursor()
        idreader(sys.argv)
        cursor.close()
        conn.close()

    except SystemExit:
        raise