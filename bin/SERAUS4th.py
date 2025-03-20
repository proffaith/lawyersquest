from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import urlsplit, parse_qsl

import requests

#import mysql.connector
import pymysql

from serpapi import GoogleSearch

#db_connection=mysql.connector.connect(host='localhost',
db_connection=pymysql.connect(
host='localhost',
user='MSBABlog',
password='44C#atlantic',
database='MSBABlog')

cursor=db_connection.cursor()

def left(s, n):
    return s[:n]

def right(string, x):
    return string[-x:]

def convert_to_mysql_date(input_string):
    date_obj = datetime.strptime(input_string, "%B %d, %Y")
    mysql_date = date_obj.strftime("%Y-%m-%d")
    return mysql_date

#  tbScrapeData
#+-------------------+--------------+------+-----+-------------------+-------------------+
#| Field             | Type         | Null | Key | Default           | Extra             |
#+-------------------+--------------+------+-----+-------------------+-------------------+
#| id                | int          | NO   | PRI | NULL              | auto_increment    |
#| docket_term       | varchar(255) | YES  |     | NULL              |                   |
#| citation          | varchar(255) | YES  |     | NULL              |                   |
#| filed_date        | date         | YES  |     | NULL              |                   |
#| judge             | varchar(255) | YES  |     | NULL              |                   |
#| parties           | varchar(255) | YES  |     | NULL              |                   |
#| date_added        | datetime     | NO   |     | CURRENT_TIMESTAMP | DEFAULT_GENERATED |
#| reviewed          | bit(1)       | NO   |     | b'0'              |                   |
#| Assignment        | int          | YES  |     | NULL              |                   |
#| Entry_Posted      | bit(1)       | YES  |     | b'0'              |                   |
#| Court             | int          | YES  |     | NULL              |                   |
#| NotesOnAssignment | text         | YES  |     | NULL              |                   |
#+-------------------+--------------+------+-----+-------------------+-------------------+



params = {
# switch back to my API key in production after 7/9/23
  "api_key": "a077e3bb4c9fda0e51957bd19a10a8839462c320aa4ed150c928ec0baff738eb",
# this key below is for testing only
#  "api_key": "399621aa2aaf0c21a875b2186d9724de7f9c5d89c830a043022a85e173877b39",
  "engine": "google_scholar",
  "q": "\"Appeal from the United States District Court for the District of Maryland\" AND (\"trade secret\" OR nondisclosure OR noncompetition)",
  "hl": "en",
  "as_ylo": "2023",
  "as_sdt": "4,124,109"

  }

search = GoogleSearch(params)
keep_going=True

while keep_going:
    try:
        results = search.get_dict()
        # Extract and process the search results from the current page
        organic_results = results["organic_results"]
        for result in organic_results:
            title = result.get("title")
            #print(title)
            link = result.get("link")
            split_link=link.split("&q")
            short_link=split_link[0]
            #print(link)
            snip=result.get('snippet')

            publication_info = result.get('publication_info', {})
            citation=publication_info.get("summary","")

            cursor=db_connection.cursor()
            query="Select Count(*) from tbscrapedata where URL = %s"
            cursor.execute(query,(short_link,))
            result=cursor.fetchone()

            record_exists = result[0] > 0

            if record_exists:
                query="UPDATE tbScrapeData set parties='"+title.replace("'","")+"',citation='"+citation.replace("'","")+"',snippet='"+snip.replace("'","")+"', URL='"+short_link+"' where URL='"+short_link+"'"
            else:
                query="INSERT INTO tbScrapeData (parties, citation, court, assignment, URL, snippet) VALUES ('"+title.replace("'","")+"','"+citation.replace("'","")+"',3,17,'"+short_link+"','"+snip.replace("'","")+"')"

            #print(query)
            cursor.execute(query)

            db_connection.commit()
            cursor.close
            db_connection.close

        if "next" in results["pagination"]:
            params.update(dict(parse_qsl(urlsplit(results["pagination"]["next"]).query)))
            search = GoogleSearch(params)
        else:
            keep_going = False

    except Exception as e:
        keep_going=False
        print(f"An error occurred while getting the search results: {str(e)}")
