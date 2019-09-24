# -*- coding: utf-8 -*-
import requests
from bs4 import BeautifulSoup
from prettytable import PrettyTable
import time
import progressbar

def finder(text, str1, str2, addition):
    a = text.find(str1)
    b = text.find(str2)
    if a != -1:
        line = text[a + addition:b]
    else:
        line = '-'
    return line

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

def idreader(steamid):
    global broken
    URL = "http://steamspy.com/api.php?request=appdetails&appid=" + steamid
    data = requests.get(URL, timeout=10).json()
    average_forever = data.get('average_forever', int())
    genres = data.get('genre', '')
    ccu = data.get('ccu', int())
    if average_forever == 0 and ccu == 0:
        if additionaltest(steamid) == 0:
            genres = '0'
            broken.append(steamid)
    elif genres != '':
        pass
    else:
        genres = '-'
    return (genres)


def homepage(steamid):
    start_time = time.time()
    url = "https://steamcommunity.com/profiles/" + steamid + "/games?tab=all&xml=1"
    data = requests.get(url)
    newdata = BeautifulSoup(data.content, 'html.parser')
    names = newdata.find_all('game')
    x = PrettyTable()
    x.field_names = ["№", "Game name", "Hours", "Genres", "SteamID"]
    counter = 0
    for i in progressbar.progressbar(range(len(names))):
        counter += 1
        tmp = str(names[i])
        line1 = finder(tmp, 'A[', ']]><', 2)
        line2 = finder(tmp, 'hoursonrecord>', '</hoursonrecord', 14)
        line3 = finder(tmp, '<appid>', '</appid', 7)
        tmp = idreader(line3)
        if tmp == '0':
            counter -=1
        else:
            if ('Utilities' not in tmp):
                x.add_row([counter, line1, line2, tmp, line3])
    print(x)
    print("--- %s seconds ---" % (time.time() - start_time))


broken = list()
yourid = str(input())
homepage(yourid)
print(broken)