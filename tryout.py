import requests
import json
from google import genai
from api import API_KEY


CAPTION_URL = "https://m.youtube.com/api/timedtext?v=tnKodkLLyN4&ei=mmnjaeO2MuCPi9oP4vHswAQ&caps=asr&opi=112496729&exp=xpe&xoaf=4&xowf=1&xospf=1&hl=en&ip=0.0.0.0&ipbits=0&expire=1776536586&sparams=ip%2Cipbits%2Cexpire%2Cv%2Cei%2Ccaps%2Copi%2Cexp%2Cxoaf&signature=DCC46E5A570D3CD50FC85E8D3C7A0834CE5DB1D2.D0AF2953AFFEB047E68514E81044E7D66F3BCE18&key=yt8&kind=asr&lang=ja&potc=1&pot=MlWBuoMtk9Xg2IGEEVKb0q_HD-ROLFhM-dzqr0EejfDw9vCGyOvwHd2QPiTSeNvuVYVY2Y9HbL5iaxJzCkDC5utUeBmn4COI-O05ksMxoXecVgpfShqL&fmt=json3&xorb=2&xobt=3&xovt=3&cbrand=google&cbr=Chrome%20Mobile&cbrver=146.0.0.0&c=MWEB&cver=2.20260415.01.00&cplayer=UNIPLAYER&cmodel=nexus%205&cos=Android&cosver=6.0&cplatform=MOBILE"

client = genai.Client(api_key=API_KEY)

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.youtube.com/",
    "Cookie": "CONSENT=YES+1;"
})

res = session.get(CAPTION_URL)
print("Status:", res.status_code)
print("Raw:", res.text[:200])

data = res.json() if res.status_code == 200 else {}

text = ""
for e in data.get("events", []):
    for s in e.get("segs", []):
        text += s.get("utf8", "") + " "

prompt = f"Translate to Slovak:\n{text}"

response = client.models.generate_content(
    model="gemini-3-flash-preview",
    contents=prompt
)

print(response.text)