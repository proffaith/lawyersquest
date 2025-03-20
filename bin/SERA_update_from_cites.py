#from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import urlsplit, parse_qsl
import re
import requests

#import mysql.connector
import pymysql

import serpapi

#db_connection=mysql.connector.connect(host='localhost',
db_connection=pymysql.connect(
host='localhost',
user='MSBABlog',
password='44C#atlantic',
database='MSBABlog')

cursorloop=db_connection.cursor()

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

# this code will loop through reviewed cases that are to be included in the study
# and will pick up cases that cite a reviewed case in any of the federal circuits/USC
# and import into the database for review

cursorloop=db_connection.cursor()
query="Select ID, URL from tbscrapedata where entry_posted=1 and URL is not null;"
cursorloop.execute(query)

while True:
    row=cursorloop.fetchone()

    if row is None:
        break

    link=row[1]
    cite=re.search(r'case=(\d+)', link).group(1)
    referring_ID=row[0]

    params = {
        #Dev Only API Key here:
      #"api_key": "399621aa2aaf0c21a875b2186d9724de7f9c5d89c830a043022a85e173877b39",

      #production API Key below:
      "api_key" : "a077e3bb4c9fda0e51957bd19a10a8839462c320aa4ed150c928ec0baff738eb",
      "engine": "google_scholar",
      "hl": "en",
      "q": "-family -divorce -employment+law -grievance -\"v. State\"",
      "as_ylo": "2023",
      "num": "20",
      "as_sdt": "4,21,146,124,109",
      "cites": cite
    #Gray v. Russell 10 F. Cas 1035
    #  "cites": "14134503684925314360"
    #Folsom v. Marsh, 9 F. Cas 342
    #  "cites": "4495747226837550380"

    }
    start_index=0
    page_size=20
    search = serpapi.search(params)
    keep_going=True

    while keep_going:
        try:
            search = serpapi.search(params)
            results = search.as_dict()

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

                citations=result.get('inline_links',{})
                cited_by=citations.get('cited_by',{})
                total=cited_by.get('total')

                if total is None:
                    total=0

                cursor=db_connection.cursor()
                query="Select Count(*) from tbscrapedata where URL = '"+short_link+"';"
                #print(query)
                cursor.execute(query)
                result=cursor.fetchone()

                record_exists = result[0] > 0

                if record_exists:
                    query="UPDATE tbscrapedata set parties='"+title.replace("'","")+"',citation='"+citation.replace("'","")+"',snippet='"+snip.replace("'","")+"', URL='"+short_link+"', cite_count="+str(total)+", cited_from="+str(referring_ID)+" where URL='"+short_link+"'"
                else:
                    query="INSERT INTO tbscrapedata (parties, citation, court, assignment, URL, snippet, cite_count, cited_from) VALUES ('"+title.replace("'","")+"','"+citation.replace("'","")+"',4,17,'"+short_link+"','"+snip.replace("'","")+"',"+str(total)+","+str(referring_ID)+")"

                print(query)
                cursor.execute(query)

                db_connection.commit()
                cursor.close
                db_connection.close

                total_results=results["search_information"]["total_results"]
                remaining_results=total_results-start_index-page_size

                if remaining_results>0:
                    start_index += page_size
                else:
                    keep_going=False

#            if "next" in results["pagination"]:
                # Extract the query parameters from the next page URL
#                next_page_params = dict(parse_qsl(urlsplit(results["pagination"]["next"]).query))

                # Update the search parameters with the next page parameters
#                params.update(next_page_params)

                # Perform the next page search
#                search = GoogleSearch(params)
#            else:
#                keep_going = False

        except Exception as e:
            keep_going=False
            print(f"An error occurred while getting the search results: {str(e)}")
