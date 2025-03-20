from datetime import datetime
from urllib.parse import urlsplit, parse_qsl
import requests
import pymysql
import serpapi
import sys
import random

courts='Md USDC'
debug_mode=False

db_connection=pymysql.connect(
host='localhost',
user='MSBABlog',
password='44C#atlantic',
database='MSBABlog')

cursor=db_connection.cursor()

# ANSI color codes for text
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"  # Reset color to default
heart_symbol = "\u2764"
diamond_symbol = "\u25C6"

# Hide the cursor
sys.stdout.write("\033[?25l")
sys.stdout.flush()

def left(s, n):
    return s[:n]

def right(string, x):
    return string[-x:]

def convert_to_mysql_date(input_string):
    date_obj = datetime.strptime(input_string, "%B %d, %Y")
    mysql_date = date_obj.strftime("%Y-%m-%d")
    return mysql_date

qs=["((Corporation OR \"limited liability company\") + (Dissolution OR \"derivative shareholder\" OR veil OR \"business judgment rule\")) -family -divorce -employment+law",
"nondisclosure or confidentiality or \"trade secret\"",
"(contract OR agreement) and breach -employment -grievance -\"v. State\" -family -divorce -HOA -\"real property\" -landlord -tenant -guardian - \"service of process\" -\"28 U.S.C. § 1441\" -\"default judgment\" - \"order of default\" -\"per curiam\" -\"leave to amend\" -\"alternate service\" -admiralty -\"Fed. R.Civ.P. 55\" -\"strict products liability\" -\"magistrate judge\" -\"motion for more definite statement\""
]

asdts=["4,146",
"4,146",
"4,146"
]

param_array = []

for q, as_dt in zip(qs, asdts):
    params = {
    # switch back to my API key in production after 7/9/23
      "api_key": "a077e3bb4c9fda0e51957bd19a10a8839462c320aa4ed150c928ec0baff738eb",
    # this key below is for testing only
    #  "api_key": "399621aa2aaf0c21a875b2186d9724de7f9c5d89c830a043022a85e173877b39",
      "engine": "google_scholar",
      "q": q,
      "hl": "en",
      "as_ylo": "2023",
      "as_sdt": as_dt

      }

    search = serpapi.search(params)
    keep_going=True
    current_line=0

    while keep_going:
        try:
            results = search.as_dict()
            # Extract and process the search results from the current page
            organic_results = results.get("organic_results",[])

            if "search_information" in results:
                search_info = results["search_information"]
                total_lines=search_info.get("total_results")
                print(f"Total Results returned: {total_lines}")
                print("", file=sys.stdout)

            for result in organic_results:
                current_line+=1

                percent_complete = round((current_line/total_lines)*100,2)
                fractional_part = random_number = random.randint(0, 10)
                if fractional_part==10:
                    pbar = heart_symbol * 10
                else:
                    pbar = diamond_symbol * int(fractional_part)

                spaces = ' ' * (10 - len(pbar))
                sys.stdout.write(f"{BLUE}Processing{RESET} [{RED}{pbar}{RESET}{spaces}] {GREEN}{percent_complete:.2f}%{RESET}")
                sys.stdout.flush()
                sys.stdout.write('\r')

                title = result.get("title")
                link = result.get("link")
                split_link=link.split("&q")
                short_link=split_link[0]
                snip=result.get('snippet')

                publication_info = result.get('publication_info', {})
                citation=publication_info.get("summary","")

                cursor=db_connection.cursor()
                query="Select Count(*) from tbscrapedata where URL = '"+short_link+"';"
                cursor.execute(query)
                result=cursor.fetchone()

                record_exists = result[0] > 0

                if debug_mode==True:
                    print(f"{record_exists}")

                if record_exists:
                    query="UPDATE tbScrapeData set parties='"+title.replace("'","")+"',citation='"+citation.replace("'","")+"',snippet='"+snip.replace("'","")+"', URL='"+short_link+"' where URL='"+short_link+"'"
                else:
                    query="INSERT INTO tbScrapeData (parties, citation, court, assignment, URL, snippet) VALUES ('"+title.replace("'","")+"','"+citation.replace("'","")+"',2,17,'"+short_link+"','"+snip.replace("'","")+"')"

                cursor.execute(query)

                db_connection.commit()
                cursor.close()

            if "pagination" in results and "next" in results["pagination"]:
                next_page_url = results["pagination"]["next"]
            else:
                next_page_url = None

            if next_page_url is not None:
                params.update(dict(parse_qsl(urlsplit(results["pagination"]["next"]).query)))
                if debug_mode==True:
                    print(f"Parameters sent: {params}")

                search = serpapi.search(params)
            else:
                keep_going = False
                #db_connection.close()

                print("", file=sys.stdout)
                print(f"Processing of {courts} cases completed")
                sys.stdout.write("\033[?25h")
                sys.stdout.flush()

        except Exception as e:
            keep_going=False
            db_connection.close()

            print("", file=sys.stdout)
            print(f"An error occurred while getting the search results: {str(e)}")
            sys.stdout.write("\033[?25h")
            sys.stdout.flush()
