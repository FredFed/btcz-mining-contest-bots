from asyncio.windows_events import NULL
from datetime import datetime, timedelta
import os
import re
import configparser
import tweepy
import pandas as pd
import requests
import pytz

import base58

### CONFIG INFO #####

# setting up date-comparison
utc=pytz.UTC

# reading API keys
config = configparser.ConfigParser()
config.read('keys.ini')
api_key = config['twitter_keys']['api_key']
api_secret = config['twitter_keys']['api_secret']
access_token = config['twitter_keys']['access_token']
token_secret = config['twitter_keys']['token_secret']

# reading config info
config.read('config.ini')
res_limit = int(config['settings']['res_limit'])
tags_needed = int(config['settings']['tags_needed'])
days_limit = int(config['settings']['days_limit'])
addr_len = int(config['settings']['addr_len'])
result_path = config['settings']['result_path']
daily_result_path = config['settings']['daily_result_path']
invalid_result_path = config['settings']['invalid_result_path']
contest_page = config['settings']['contest_page']
pools = [config['settings']['pool_one'],
        config['settings']['pool_two'],
        config['settings']['pool_three']]

# authenticating to Twitter
auth = tweepy.OAuthHandler(api_key, api_secret)
auth.set_access_token(access_token, token_secret)
api = tweepy.API(auth)



### FUNCTIONS ###

# checks if the user is following BTCZOfficial
def isBTCZFollower(user):
    status = api.get_friendship(source_screen_name=user, target_screen_name="BTCZOfficial")
    if status[0].following:
        return True
    else:
        return False


# checks if the tweet's date is older than a month (not eligible)
def isDateValid(date):
    date = utc.localize(datetime.strptime(date, "%Y-%m-%d %H:%M:%S+00:00"))
    expiration = datetime.utcnow() - timedelta(days=days_limit)
    if date > utc.localize(expiration):
        return True
    else:
        return False


# checks if the tweet's format is correct
def tweetChecker(user, address, text, page_tagged):
    if not isBTCZFollower(user):
        return False
    if address=="no_addr":
        return False
    if text.count('@') < tags_needed:
        return False
    if not page_tagged:
        return False
    if text.find("via @") != -1:
        return False
    return True


# checks if the entry is duplicate
def isDuplicate(id, old_df):
    for index, row in old_df.iterrows():
        if str(row['TweetID'])==str(id):
            return True
    return False


# extracts all links from the text given
def getLinks(text):
    links = []
    tokens = text.split()
    for token in tokens:
        if token.find('http') != -1:
            i = token.find('http')
            links.append(token[i:i+23])
    return links


# extracts information from the link
def getLinkLocation(link):
    res = requests.get(link, allow_redirects=False)
    print(str(res.status_code)+" "+str(res.headers["location"]))
    return res.headers["location"]


# returns, if present, the pool the user is mining on
def getPool(links):
    print(links)
    if not links:
        return "no_pool"
    for link in links:
        url = getLinkLocation(link)
        for pool in pools:
            if url.find(pool) != -1:
                return pool
    return "no_pool"


# checks if the contest link has been used
def checkMainLink(links):
    if not links:
        return False
    for link in links:
        url = getLinkLocation(link)
        if url.find(contest_page) != -1:
            return True
    return False


# returns, if present, the partecipant address
def getAddressOld(text):
    tokens = text.split()
    for token in tokens:
        i = token.find('t')
        if i != -1 and (len(token[i:]) == (addr_len)) and re.search('^.[1-9]', token[i:]) and re.search('^[a-zA-Z1-9][^OIl]+$', token[i:]):
            return token[i:]
    return "no_addr"

def getAddress(text):
    index=-1
    while True:
        index=text.find("t",index+1)
        if index==-1:
            return "no_addr"
        if (len(text[index:]) >= (addr_len)):
            token=text[index:index+addr_len]
            if base58.validAddress(token):
                return token



# FETCHING method
def fetchTweets():
    # specifying fetch parameters
    keywords = '@BTCZOfficial #BTCZmining -filter:retweets'

    tweets = tweepy.Cursor(api.search_tweets, q=keywords, count=100, tweet_mode='extended').items(res_limit)

    # data frame creation
    df = NULL
    invalid_df = NULL
    columns = ['TweetID', 'User', 'Address', 'Date', 'Tweet', 'Likes', 'MainTag']
    data = []
    invalid_data = []

    if not os.path.exists(result_path):
        df = pd.DataFrame(data, columns=columns)
    else:
        df = pd.read_csv(result_path)
    
    if not os.path.exists(invalid_result_path):
        invalid_df = pd.DataFrame(invalid_data, columns=columns)
    else:
        invalid_df = pd.read_csv(invalid_result_path)
    
    count = 1
    # selecting only the correctly formatted posts
    for tweet in tweets:
        count+=1
        # getting tweet's fields
        text = tweet.full_text
        id = tweet.id_str
        user = tweet.user.screen_name
        date = tweet.created_at
        likes = tweet.favorite_count

        # getting row's info
        links = getLinks(text)
        page_tagged = checkMainLink(links)
        address = getAddress(text)
        
        if tweetChecker(user, address, text, page_tagged):
            if not isDuplicate(id, df):
                data.append([id, user, address, date, text, likes, page_tagged])
        else:
            if not isDuplicate(id, invalid_df):
                invalid_data.append([id, user, address, date, text, likes, page_tagged])
    
    # concatenating dataframes
    temp_df = pd.DataFrame(data, columns=columns)
    temp_invalid_df = pd.DataFrame(invalid_data, columns=columns)
    temp_df.sort_values(by='Date', ascending=False)
    temp_invalid_df.sort_values(by='Date', ascending=False)
    new_df = pd.concat([df, temp_df], axis=0, join='outer')
    new_invalid_df = pd.concat([invalid_df, temp_invalid_df], axis=0, join='outer')

    # preview print
    if not temp_df.empty:
        print("########## NEW VALID TWEETS ##########")
        print(temp_df)
        print("")
    else:
        print("No new valid tweets\n")

    # preview print
    if not temp_invalid_df.empty:
        print("########## NEW INVALID TWEETS ##########")
        print(temp_invalid_df)
        print("")
    else:
        print("No new invalid tweets\n")

    # creating a dump of the dataframes on file
    new_df.to_csv(result_path, mode='w', index=False)
    new_invalid_df.to_csv(invalid_result_path, mode='w', index=False)


# remove rows older than 30 days
def discardOld():
    df = pd.read_csv(result_path)

    columns = ['TweetID', 'User', 'Address', 'Date', 'Tweet', 'Likes']
    data = []

    for index, row in df.iterrows():
        if isDateValid(row['Date']):
            data.append(row)
    
    new_df = pd.DataFrame(data, columns=columns)
    new_df.to_csv(result_path, mode='w', index=False)

    invalid_df = pd.read_csv(invalid_result_path)

    columns = ['TweetID', 'User', 'Address', 'Date', 'Tweet', 'Likes']
    data = []

    for index, row in invalid_df.iterrows():
        if isDateValid(row['Date']):
            data.append(row)
    
    new_invalid_df = pd.DataFrame(data, columns=columns)
    new_invalid_df.to_csv(invalid_result_path, mode='w', index=False)


# updates the likes of each entry
def updateLikes():
    df = pd.read_csv(result_path)
    for index, row in df.iterrows():
        tweet_id = row['TweetID']
        try:
            tweet = api.get_status(tweet_id)
            df.loc[index, 'Likes'] = tweet.favorite_count
        except Exception as e:
            print(str(tweet_id)+": "+str(e))
            if str(e).find('63 -') != -1: #63 - User has been suspended.
                df.loc[index, 'Likes'] = -1
            elif str(e).find('144 -') != -1: #144 - No status found with that ID.
                df.loc[index, 'Likes'] = -1 
            elif str(e).find('179 -') != -1: #179 - Sorry, you are not authorized to see this status.
                df.loc[index, 'Likes'] = -1 

    df.to_csv(result_path, index=False)

    #invalid_df = pd.read_csv(invalid_result_path)
    #for index, row in invalid_df.iterrows():
    #    tweet_id = row['TweetID']
    #    try:
    #        tweet = api.get_status(tweet_id)
    #        invalid_df.loc[index, 'Likes'] = tweet.favorite_count
    #    except Exception as e:
    #        print(e)
    #invalid_df.to_csv(invalid_result_path, index=False)

def getUTCString(dayOffset=0,delimiter="."):
    now = datetime.utcnow() + timedelta(days=dayOffset) 
    return str('{:04d}'.format(now.year))+delimiter+str('{:02d}'.format(now.month))+delimiter+str('{:02d}'.format(now.day))

def exportTodayLikes():
    df = pd.read_csv(result_path)
    today_df = df.drop('Tweet', axis=1)
    today_df.to_csv(daily_result_path+getUTCString()+".csv", mode='w', index=False)


def main():
    ### MAIN ###
    print("fetchTweets")
    fetchTweets()
    print("discardOld")
    discardOld()
    print("updateLikes")
    updateLikes()
    print("exportTodayLikes")
    exportTodayLikes()
    ### END ###

if __name__ == "__main__":
    main()